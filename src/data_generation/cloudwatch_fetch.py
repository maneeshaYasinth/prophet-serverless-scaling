"""Pull sandbox-lambda metrics from CloudWatch into a Prophet-ready CSV.

Output columns:
    ds           timestamp (tz-naive, 1-minute steps; Prophet requires tz-naive)
    y            invocations per minute (the series Prophet forecasts)
    concurrency  max concurrent executions in that minute (Layer 1 regressor)
    duration_ms  average duration in that minute (Layer 1 regressor)

Usage:
    python cloudwatch_fetch.py --minutes 90 --out data/seasonal_run1.csv
"""
import argparse
from datetime import datetime, timedelta, timezone

import boto3
import pandas as pd

REGION = "ap-south-1"
FUNCTION = "sandbox-lambda"
ALIAS = "prod"
PERIOD_S = 60

# output column -> (CloudWatch metric name, statistic)
METRICS = {
    "y": ("Invocations", "Sum"),
    "concurrency": ("ConcurrentExecutions", "Maximum"),
    "duration_ms": ("Duration", "Average"),
}


def fetch(start, end, period=PERIOD_S, function=FUNCTION, alias=ALIAS, region=REGION):
    cw = boto3.client("cloudwatch", region_name=region)
    dims = [
        {"Name": "FunctionName", "Value": function},
        {"Name": "Resource", "Value": f"{function}:{alias}"},
    ]
    queries = [
        {
            "Id": col,
            "MetricStat": {
                "Metric": {"Namespace": "AWS/Lambda", "MetricName": name, "Dimensions": dims},
                "Period": period,
                "Stat": stat,
            },
            "ReturnData": True,
        }
        for col, (name, stat) in METRICS.items()
    ]

    series, token = {}, None
    while True:
        kwargs = dict(MetricDataQueries=queries, StartTime=start, EndTime=end,
                      ScanBy="TimestampAscending")
        if token:
            kwargs["NextToken"] = token
        resp = cw.get_metric_data(**kwargs)
        for result in resp["MetricDataResults"]:
            series.setdefault(result["Id"], {}).update(zip(result["Timestamps"], result["Values"]))
        token = resp.get("NextToken")
        if not token:
            break

    df = pd.DataFrame(series)
    if df.empty:
        raise SystemExit("No datapoints returned - check the time window and alias.")

    df = df.sort_index()
    df.index = df.index.tz_convert(None)

    # CloudWatch omits minutes with no activity, so rebuild a regular grid.
    grid = pd.date_range(df.index.min(), df.index.max(), freq=f"{period}s")
    df = df.reindex(grid)
    df["y"] = df["y"].fillna(0)                      # no datapoint = no invocations
    df["concurrency"] = df["concurrency"].fillna(0)
    df["duration_ms"] = df["duration_ms"].ffill()    # regressors can't be NaN in Prophet

    return df.rename_axis("ds").reset_index()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=int, default=90, help="how far back to fetch")
    p.add_argument("--out", default="cloudwatch_metrics.csv")
    args = p.parse_args()

    # Stop 3 minutes short of now: CloudWatch publishes Lambda metrics
    # with a short delay, so the latest minutes are often incomplete.
    end = datetime.now(timezone.utc) - timedelta(minutes=3)
    start = end - timedelta(minutes=args.minutes)

    df = fetch(start, end)
    df.to_csv(args.out, index=False)
    print(f"Saved {len(df)} rows to {args.out}")
    print(df.describe().round(2))


if __name__ == "__main__":
    main()
