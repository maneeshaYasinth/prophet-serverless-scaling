"""
Live forecast -> Provisioned Concurrency loop (C2, optionally C3 Layer 2).

Every minute:
    1. take the newest W complete minutes of CloudWatch data (ds, y)
    2. fit Prophet on them and forecast the minutes this decision is in charge of
    3. convert the forecast peak to a target with the calibrated CapacityModel
    4. (--apply only) put_provisioned_concurrency_config if the target changed
    5. append the decision to results/controller/<run>.csv

Timing (configs/experiment_config.yaml, controller section): CloudWatch data is
complete up to now - cloudwatch_delay, and capacity set now is ready after
pc_ready and replaced one step later. So the decision made at `now` covers the
minutes [now + pc_ready, now + pc_ready + step], and the target is the peak
forecast over exactly those minutes.

Modes:
    --replay CSV   simulated clock over a saved CloudWatch CSV; no AWS calls
    (default)      live, dry run: reads CloudWatch, decides, never touches PC
    --apply        live, sets Provisioned Concurrency; deletes the PC config on
                   exit (normal end, error, Ctrl-C or SIGTERM) so nothing is left billing

Usage (from the repo root):
    python -m src.controller.live_controller --replay data/processed/seasonal_train_run1.csv
    python -m src.controller.live_controller --minutes 90            # live dry run
    python -m src.controller.live_controller --minutes 90 --apply    # live, changes AWS
"""

import argparse
import csv
import logging
import signal
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yaml

from src.controller.capacity_model import CapacityModel
from src.evaluation.rolling_forecast import CONFIG_PATH, REPO_ROOT
from src.forecasting.prophet_baseline import fit_vanilla_prophet

RESULTS_DIR = REPO_ROOT / "results" / "controller"
FORECAST_FIELD = {"c2": "yhat", "c3-layer2": "yhat_upper"}  # C2 and C3 differ only in this field
TICK_OFFSET_S = 5  # decide a few seconds after each minute boundary


def plan(history: pd.DataFrame, now: pd.Timestamp, cfg: dict, capacity_model: CapacityModel,
         field: str, pattern: str) -> dict:
    """
    One decision. Pure: no AWS, no clock. `history` has ds (tz-naive UTC
    minute starts) and y; only rows with ds < now - cloudwatch_delay are used,
    so nothing the controller could not have seen at `now` leaks in.
    """
    ctl, fc = cfg["controller"], cfg["forecasting"]
    roll = fc["rolling"]
    window, step = roll["training_window_minutes"], roll["step_minutes"]
    data_end = now - pd.Timedelta(minutes=ctl["cloudwatch_delay_minutes"])
    train = history[history.ds < data_end].tail(window)

    row = {"now": now, "n_train": len(train), "last_data": train.ds.max() if len(train) else None}
    if len(train) < window:
        return {**row, "status": "warming_up", "target": None}

    first = now + pd.Timedelta(minutes=ctl["pc_ready_minutes"])
    covered = pd.DataFrame({"ds": [first + pd.Timedelta(minutes=i) for i in range(step + 1)]})
    steps_ahead = int((covered.ds.iloc[-1] - train.ds.iloc[-1]) / pd.Timedelta(minutes=1))
    if steps_ahead > fc["lead_time_minutes"]:
        raise ValueError(f"decision needs a {steps_ahead}-min forecast, beyond lead_time_minutes")

    model = fit_vanilla_prophet(
        train[["ds", "y"]],
        interval_width=fc["confidence_interval"],
        seasonality_period_minutes=cfg["traffic_patterns"][pattern].get("period_minutes"),
        fourier_order=roll["fourier_order"],
    )
    fcst = model.predict(covered)
    used = float(fcst[field].max())
    return {
        **row,
        "status": "ok",
        "covers_from": covered.ds.iloc[0],
        "covers_to": covered.ds.iloc[-1],
        "steps_ahead": steps_ahead,
        "yhat_max": round(float(fcst.yhat.max()), 1),
        "yhat_upper_max": round(float(fcst.yhat_upper.max()), 1),
        "target": capacity_model.target(used),
    }


class DecisionLog:
    """Appends one CSV row per decision and flushes, so a crash keeps the data."""

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self._f, self._w = path, open(path, "w", newline=""), None

    def write(self, row: dict):
        if self._w is None:
            self._w = csv.DictWriter(self._f, fieldnames=list(row), extrasaction="ignore")
            self._w.writeheader()
        self._w.writerow(row)
        self._f.flush()

    def close(self):
        self._f.close()


# Every key any row can have, so the CSV header is stable whatever the first row's status
FIELDS = ["now", "status", "n_train", "last_data", "covers_from", "covers_to", "steps_ahead",
          "yhat_max", "yhat_upper_max", "target", "applied", "pc_status", "pc_allocated",
          "actual_peak_concurrency", "error"]


def run_replay(args, cfg, capacity_model, field, log):
    history = pd.read_csv(args.replay, parse_dates=["ds"])
    step = pd.Timedelta(minutes=cfg["forecasting"]["rolling"]["step_minutes"])
    now, rows = history.ds.min(), []
    while now <= history.ds.max():
        d = plan(history, now, cfg, capacity_model, field, args.pattern)
        if d["status"] == "ok" and "concurrency" in history:
            seen = history[(history.ds >= d["covers_from"]) & (history.ds <= d["covers_to"])]
            if len(seen) == len(pd.date_range(d["covers_from"], d["covers_to"], freq="min")):
                d["actual_peak_concurrency"] = int(seen.concurrency.max())  # scoring only, after the fact
        log.write({k: d.get(k) for k in FIELDS})
        rows.append(d)
        now += step

    df = pd.DataFrame(rows)
    ok = df[df.status == "ok"].dropna(subset=["actual_peak_concurrency"])
    gap = ok.target - ok.actual_peak_concurrency
    print(f"replay: {len(df)} ticks, {int((df.status == 'warming_up').sum())} warming up, {len(ok)} scored")
    if len(ok):
        print(f"under-provisioned decisions: {int((gap < 0).sum())}/{len(ok)}   "
              f"mean excess: {gap.clip(lower=0).mean():.1f} env   target range: {ok.target.min()}-{ok.target.max()}")


def run_live(args, cfg, capacity_model, field, log):
    import boto3
    from botocore.exceptions import ClientError

    from src.controller.provisioned_concurrency import set_provisioned_concurrency
    from src.data_generation.cloudwatch_fetch import fetch

    aws, ctl = cfg["aws"], cfg["controller"]
    fn, alias, region = aws["function_name"], aws["alias"], aws["region"]
    lam = boto3.client("lambda", region_name=region)
    lookback = cfg["forecasting"]["rolling"]["training_window_minutes"] + ctl["cloudwatch_delay_minutes"] + 5
    last_applied = None
    deadline = time.time() + args.minutes * 60

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        while time.time() < deadline:
            wall = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            now = pd.Timestamp(wall).tz_convert(None)
            row = {"now": now}
            try:
                history = fetch(wall - timedelta(minutes=lookback), wall, function=fn, alias=alias, region=region)
                row = plan(history, now, cfg, capacity_model, field, args.pattern)
            except SystemExit as e:  # fetch() exits when CloudWatch has no datapoints yet
                row.update(status="no_data", error=str(e))

            if args.apply and row.get("target") is not None and row["target"] != last_applied:
                try:
                    set_provisioned_concurrency(fn, alias, int(row["target"]), region=region)
                    last_applied, row["applied"] = row["target"], True
                except ClientError as e:  # e.g. an update still in progress; retried next tick
                    row["error"] = e.response["Error"]["Code"]
            if args.apply:
                try:
                    pc = lam.get_provisioned_concurrency_config(FunctionName=fn, Qualifier=alias)
                    row.update(pc_status=pc["Status"], pc_allocated=pc.get("AllocatedProvisionedConcurrentExecutions"))
                except lam.exceptions.ProvisionedConcurrencyConfigNotFoundException:
                    row.update(pc_status="none", pc_allocated=0)

            log.write({k: row.get(k) for k in FIELDS})
            print(f"{now:%H:%M} {row.get('status'):>10}  train={row.get('n_train')}  "
                  f"target={row.get('target')}  pc={row.get('pc_allocated', '-')}  {row.get('error') or ''}")

            next_tick = (wall + timedelta(minutes=1)).timestamp() + TICK_OFFSET_S
            time.sleep(max(0.0, next_tick - time.time()))
    except KeyboardInterrupt:
        print("stopping...")
    finally:
        if args.apply:
            try:
                lam.delete_provisioned_concurrency_config(FunctionName=fn, Qualifier=alias)
                print("Provisioned Concurrency config deleted.")
            except lam.exceptions.ResourceNotFoundException:
                print("No Provisioned Concurrency config to delete.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--condition", choices=sorted(FORECAST_FIELD), default="c2")
    p.add_argument("--pattern", default="seasonal", help="traffic_patterns key in the config")
    p.add_argument("--replay", help="CloudWatch CSV to replay with a simulated clock (no AWS calls)")
    p.add_argument("--minutes", type=int, default=90, help="live run length")
    p.add_argument("--apply", action="store_true", help="actually set Provisioned Concurrency")
    args = p.parse_args()
    if args.apply and args.replay:
        p.error("--apply cannot be combined with --replay")

    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    ctl = cfg["controller"]
    capacity_model = CapacityModel.load(
        REPO_ROOT / ctl["calibration_file"],
        buffer_percent=cfg["aws"]["pc_buffer_percent"],
        max_concurrency=ctl["max_provisioned_concurrency"],
    )
    logging.getLogger("cmdstanpy").disabled = True
    np.random.seed(cfg["forecasting"]["rolling"]["random_seed"])

    mode = "replay" if args.replay else ("apply" if args.apply else "dryrun")
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    log = DecisionLog(RESULTS_DIR / f"{stamp}_{args.condition}_{args.pattern}_{mode}.csv")
    field = FORECAST_FIELD[args.condition]
    try:
        if args.replay:
            run_replay(args, cfg, capacity_model, field, log)
        else:
            run_live(args, cfg, capacity_model, field, log)
    finally:
        log.close()
        print(f"Decisions saved to {log.path}")


if __name__ == "__main__":
    main()
