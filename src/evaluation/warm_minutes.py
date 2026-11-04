"""
Drop cold-start-burst minutes from a run's CloudWatch CSV before capacity calibration.

A minute in which clients felt cold starts (response above
evaluation.felt_cold_start_ms) has inflated ConcurrentExecutions: each new
environment is held for its ~3 s init, so a burst of 60-90 inits pushes the
per-minute peak to 100-130 where warm traffic at the same rate needs 75-90
(Run 2026-11-04-1). Provisioned Concurrency is meant to remove exactly those
inits, so the calibration should describe warm demand only.

Adds a felt_cold_starts column (from the run's invoke log) and writes
<cloudwatch>_warm.csv without the minutes that had any.

Usage (from the repo root):
    python -m src.evaluation.warm_minutes data/processed/spiky_c1_ec2_run2.csv \
        data/raw/20261104-0439_spiky_c1_traffic.jsonl
"""

import argparse
from pathlib import Path

import pandas as pd
import yaml

from src.evaluation.rolling_forecast import CONFIG_PATH


def felt_per_minute(invoke_log: str, threshold_ms: float) -> pd.Series:
    """Felt cold starts per UTC minute in which the request started, read in chunks (spiky
    invoke logs are ~500 MB). The log's timestamp is taken when the response arrives, so an
    init that began at :57 would otherwise land in the next minute, while CloudWatch counts
    its environment in the minute it started (Run 2026-11-03-2, 15:50: concurrency 115)."""
    counts = []
    for chunk in pd.read_json(invoke_log, lines=True, convert_dates=False, chunksize=500_000,
                              dtype={"error": object}):
        felt = chunk[chunk.response_time_ms > threshold_ms]
        started = felt.timestamp - felt.response_time_ms / 1000
        counts.append(pd.to_datetime(started, unit="s").dt.floor("min").value_counts())
    return pd.concat(counts).groupby(level=0).sum()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cloudwatch", help="the run's CloudWatch CSV with ds, y, concurrency")
    p.add_argument("invoke_log", help="the run's Locust invoke log (data/raw/RUN.jsonl)")
    args = p.parse_args()

    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    threshold_ms = cfg["evaluation"]["felt_cold_start_ms"]
    df = pd.read_csv(args.cloudwatch, parse_dates=["ds"])
    df["felt_cold_starts"] = df.ds.map(felt_per_minute(args.invoke_log, threshold_ms)).fillna(0).astype(int)
    warm = df[df.felt_cold_starts == 0]

    out = Path(args.cloudwatch).with_name(Path(args.cloudwatch).stem + "_warm.csv")
    warm.to_csv(out, index=False)
    dropped = df[df.felt_cold_starts > 0]
    print(f"Dropped {len(dropped)} of {len(df)} minutes with felt cold starts "
          f"({dropped.felt_cold_starts.sum()} in total); saved {out}")


if __name__ == "__main__":
    main()
