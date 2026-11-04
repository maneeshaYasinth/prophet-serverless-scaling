"""
Live forecast -> Provisioned Concurrency loop (C2, optionally C3 Layer 2).

Every minute:
    1. take the newest W complete minutes of CloudWatch data (ds, y)
    2. fit Prophet on them and forecast the minutes this decision is in charge of
    3. convert the forecast peaks to targets with the calibrated CapacityModel
    4. decide whether to raise, lower, keep or hold the configured PC (decide())
    5. (--apply only) put_provisioned_concurrency_config if it changes
    6. append the decision to results/controller/<run>.csv

Timing (configs/experiment_config.yaml, controller section): CloudWatch data is
complete up to now - cloudwatch_delay, and capacity set now is ready after
pc_ready and replaced one step later. So the decision made at `now` covers the
minutes [now + pc_ready, now + pc_ready + step], and the target is the peak
forecast over exactly those minutes.

Scale-up policy (controller.scale_up_policy). A raise needs about 84 s to become
usable, and a new put while it is IN_PROGRESS restarts it: re-targeting every
minute kept usable PC stuck at 9 while the API reported up to 22 (Run 2026-11-01-1,
Known issue 14). With "wait_for_ready" a raise is sent only when the config is
READY, so it may stay in charge until the next raise lands one pc_ready later:
raises use target_up, the peak over [now + pc_ready, now + 2 pc_ready + step].
Lowering takes about 12 s, so a lower target is applied at once.
"every_minute" is the old behaviour, kept for comparison.

pc_status and pc_allocated are read before each decision (the state it was made
in); in replay and dry runs they come from SimulatedPC.

Modes:
    --replay CSV   simulated clock over a saved CloudWatch CSV; no AWS calls;
                   scores the usable PC each minute against measured concurrency
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
         field: str, pattern: str, history_start: pd.Timestamp | None = None) -> dict:
    """
    One decision. Pure: no AWS, no clock. `history` has ds (tz-naive UTC
    minute starts) and y; only rows with ds < now - cloudwatch_delay are used,
    so nothing the controller could not have seen at `now` leaks in.

    history_start drops earlier rows. Without it, an earlier session inside the
    fetch lookback (plus the zero-filled gap after it) enters the training
    window: Run 2026-10-16-2's first 10 decisions trained on a smoke test from
    30 minutes before and were off by up to 40%.
    """
    ctl, fc = cfg["controller"], cfg["forecasting"]
    roll = fc["rolling"]
    window, step = roll["training_window_minutes"], roll["step_minutes"]
    data_end = now - pd.Timedelta(minutes=ctl["cloudwatch_delay_minutes"])
    if history_start is not None:
        history = history[history.ds >= history_start]
    train = history[history.ds < data_end].tail(window)

    row = {"now": now, "n_train": len(train), "last_data": train.ds.max() if len(train) else None}
    if len(train) < window:
        return {**row, "status": "warming_up", "target": None}

    first = now + pd.Timedelta(minutes=ctl["pc_ready_minutes"])
    # A raise blocks further raises until READY, so it must also cover one more pc_ready
    up_extra = ctl["pc_ready_minutes"] if ctl["scale_up_policy"] == "wait_for_ready" else 0
    horizon = pd.DataFrame({"ds": [first + pd.Timedelta(minutes=i) for i in range(step + up_extra + 1)]})
    covered = horizon.iloc[:step + 1]
    steps_ahead = int((horizon.ds.iloc[-1] - train.ds.iloc[-1]) / pd.Timedelta(minutes=1))
    if steps_ahead > fc["lead_time_minutes"]:
        raise ValueError(f"decision needs a {steps_ahead}-min forecast, beyond lead_time_minutes")

    model = fit_vanilla_prophet(
        train[["ds", "y"]],
        interval_width=fc["confidence_interval"],
        seasonality_period_minutes=cfg["traffic_patterns"][pattern].get("period_minutes"),
        fourier_order=roll["fourier_order"],
    )
    fcst = model.predict(horizon)
    short = fcst.iloc[:step + 1]
    return {
        **row,
        "status": "ok",
        "covers_from": covered.ds.iloc[0],
        "covers_to": covered.ds.iloc[-1],
        "covers_up_to": horizon.ds.iloc[-1],
        "steps_ahead": steps_ahead,
        "yhat_max": round(float(short.yhat.max()), 1),
        "yhat_upper_max": round(float(short.yhat_upper.max()), 1),
        "target": capacity_model.target(float(short[field].max())),
        "target_up": capacity_model.target(float(fcst[field].max())),
    }


def decide(target, target_up, configured: int, pc_status: str, usable: int,
           policy: str) -> tuple[int, str | None]:
    """
    The scaling rule. Pure. Returns (PC to configure, action), action one of
    raise / lower / keep / held (a change wanted, but a put would restart the
    allocation still IN_PROGRESS), or set (every_minute policy); None when there
    is no target yet. usable = environments already allocated.
    """
    if target is None:
        return configured, None
    if policy == "every_minute":
        return (target, "set") if target != configured else (configured, "keep")
    if target_up > configured:
        if pc_status in ("READY", "none"):
            return target_up, "raise"
        return configured, "held"  # a put now would restart the allocation (Known issue 14)
    if target < configured:
        # Mid-raise, a value still above what is usable is a new raise and restarts it
        if pc_status == "IN_PROGRESS" and target > usable:
            return configured, "held"
        return target, "lower"
    return configured, "keep"


class SimulatedPC:
    """
    Stands in for Provisioned Concurrency in replay and dry runs. A raise becomes
    usable pc_ready minutes after it is set (measured 84 s, rounded up); a put while
    a raise is IN_PROGRESS restarts it, as observed in Run 2026-11-01-1; a lower is
    usable at once (measured 12.5 s).
    """

    def __init__(self, ready_minutes: int):
        self.ready = pd.Timedelta(minutes=ready_minutes)
        self.value = self.usable = 0
        self.ready_at = None

    def set(self, value: int, now: pd.Timestamp):
        self._advance(now)
        self.value = value
        if value <= self.usable:
            self.usable, self.ready_at = value, now
        else:
            self.ready_at = now + self.ready

    def state(self, now: pd.Timestamp) -> tuple[str, int]:
        self._advance(now)
        if self.ready_at is None:
            return "none", 0
        return ("READY" if now >= self.ready_at else "IN_PROGRESS"), self.usable

    def _advance(self, now):
        if self.ready_at is not None and now >= self.ready_at:
            self.usable = self.value


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
FIELDS = ["now", "status", "n_train", "last_data", "covers_from", "covers_to", "covers_up_to",
          "steps_ahead", "yhat_max", "yhat_upper_max", "target", "target_up", "pc_status",
          "pc_allocated", "action", "configured", "applied", "actual_concurrency", "error"]


def run_replay(args, cfg, capacity_model, field, log):
    history = pd.read_csv(args.replay, parse_dates=["ds"])
    ctl = cfg["controller"]
    step = pd.Timedelta(minutes=cfg["forecasting"]["rolling"]["step_minutes"])
    pc, configured = SimulatedPC(ctl["pc_ready_minutes"]), 0
    actual = history.set_index("ds").concurrency if "concurrency" in history else None
    now, rows = history.ds.min(), []
    while now <= history.ds.max():
        d = plan(history, now, cfg, capacity_model, field, args.pattern)
        d["pc_status"], d["pc_allocated"] = pc.state(now)  # usable this minute
        configured, d["action"] = decide(d.get("target"), d.get("target_up"), configured,
                                         d["pc_status"], d["pc_allocated"], ctl["scale_up_policy"])
        if d["action"] in ("raise", "lower", "set"):
            pc.set(configured, now)
        d["configured"] = configured
        if actual is not None and now in actual.index:
            d["actual_concurrency"] = int(actual[now])  # scoring only, after the fact
        log.write({k: d.get(k) for k in FIELDS})
        rows.append(d)
        now += step

    df = pd.DataFrame(rows)
    acts = df.action.value_counts().to_dict()
    print(f"replay ({ctl['scale_up_policy']}): {len(df)} ticks, "
          f"{int((df.status == 'warming_up').sum())} warming up, actions {acts}")
    # Score every minute from the first one PC could be usable until the data ends
    first = df[df.status == "ok"].covers_from.min()
    scored = df[(df.now >= first)].dropna(subset=["actual_concurrency"])
    if len(scored):
        gap = scored.pc_allocated - scored.actual_concurrency
        print(f"minutes with usable PC below measured concurrency: {int((gap < 0).sum())}/{len(scored)}   "
              f"shortfall {(-gap).clip(lower=0).sum():.0f} env-min   "
              f"configured {scored.configured.sum():.0f} env-min   usable range {scored.pc_allocated.min()}-{scored.pc_allocated.max()}")


def run_live(args, cfg, capacity_model, field, log):
    import boto3
    from botocore.exceptions import ClientError

    from src.controller.provisioned_concurrency import set_provisioned_concurrency
    from src.data_generation.cloudwatch_fetch import fetch

    aws, ctl = cfg["aws"], cfg["controller"]
    fn, alias, region = aws["function_name"], aws["alias"], aws["region"]
    lam = boto3.client("lambda", region_name=region)
    lookback = cfg["forecasting"]["rolling"]["training_window_minutes"] + ctl["cloudwatch_delay_minutes"] + 5
    sim = None if args.apply else SimulatedPC(ctl["pc_ready_minutes"])
    configured = 0
    deadline = time.time() + args.minutes * 60

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)  # tmux kill-session or the instance shutting down
    try:
        while time.time() < deadline:
            wall = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            now = pd.Timestamp(wall).tz_convert(None)
            row = {"now": now}
            try:
                history = fetch(wall - timedelta(minutes=lookback), wall, function=fn, alias=alias, region=region)
                row = plan(history, now, cfg, capacity_model, field, args.pattern, args.history_start)
            except SystemExit as e:  # fetch() exits when CloudWatch has no datapoints yet
                row.update(status="no_data", error=str(e))

            row["pc_status"], row["pc_allocated"] = read_pc(lam, fn, alias) if args.apply else sim.state(now)
            new, row["action"] = decide(row.get("target"), row.get("target_up"), configured,
                                        row["pc_status"], row["pc_allocated"], ctl["scale_up_policy"])
            if row["action"] in ("raise", "lower", "set"):
                if args.apply:
                    try:
                        set_provisioned_concurrency(fn, alias, int(new), region=region)
                        configured, row["applied"] = new, True
                    except ClientError as e:  # e.g. a conflict; decided again next tick
                        row["error"] = e.response["Error"]["Code"]
                else:
                    sim.set(new, now)
                    configured = new
            row["configured"] = configured

            log.write({k: row.get(k) for k in FIELDS})
            print(f"{now:%H:%M} {row.get('status'):>10}  train={row.get('n_train')}  "
                  f"target={row.get('target')}/{row.get('target_up')}  {row.get('action') or '':>5} "
                  f"configured={configured}  pc={row.get('pc_status')}:{row.get('pc_allocated')}  {row.get('error') or ''}")

            next_tick = (wall + timedelta(minutes=1)).timestamp() + TICK_OFFSET_S
            time.sleep(max(0.0, next_tick - time.time()))
    except KeyboardInterrupt:
        print("stopping...")
    finally:
        if args.apply:
            delete_provisioned_concurrency(lam, fn, alias)


def read_pc(lam, fn, alias) -> tuple[str, int]:
    try:
        pc = lam.get_provisioned_concurrency_config(FunctionName=fn, Qualifier=alias)
        return pc["Status"], pc.get("AllocatedProvisionedConcurrentExecutions") or 0
    except lam.exceptions.ProvisionedConcurrencyConfigNotFoundException:
        return "none", 0


def delete_provisioned_concurrency(lam, fn, alias, attempts=12, wait_s=10):
    """Delete the PC config, retrying while an allocation is still IN_PROGRESS (ResourceConflict)."""
    for _ in range(attempts):
        try:
            lam.delete_provisioned_concurrency_config(FunctionName=fn, Qualifier=alias)
            print("Provisioned Concurrency config deleted.")
            return
        except (lam.exceptions.ResourceNotFoundException,
                lam.exceptions.ProvisionedConcurrencyConfigNotFoundException):
            print("No Provisioned Concurrency config to delete.")
            return
        except lam.exceptions.ResourceConflictException:
            time.sleep(wait_s)
    print(f"WARNING: could not delete Provisioned Concurrency on {fn}:{alias}; it is still billing. "
          f"Run: aws lambda delete-provisioned-concurrency-config --function-name {fn} --qualifier {alias}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--condition", choices=sorted(FORECAST_FIELD), default="c2")
    p.add_argument("--pattern", default="seasonal", help="traffic_patterns key in the config")
    p.add_argument("--replay", help="CloudWatch CSV to replay with a simulated clock (no AWS calls)")
    p.add_argument("--minutes", type=int, default=90, help="live run length")
    p.add_argument("--apply", action="store_true", help="actually set Provisioned Concurrency")
    p.add_argument("--policy", choices=["wait_for_ready", "every_minute"],
                   help="override controller.scale_up_policy (e.g. to replay the old behaviour)")
    p.add_argument("--run-name", help="decision log file name (default: timestamp_condition_pattern_mode)")
    p.add_argument("--history-start", type=pd.Timestamp,
                   help="UTC minute (e.g. 2026-10-16T19:08); ignore CloudWatch data before it")
    args = p.parse_args()
    if args.apply and args.replay:
        p.error("--apply cannot be combined with --replay")

    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    ctl = cfg["controller"]
    if args.policy:
        ctl["scale_up_policy"] = args.policy
    calibration_file = ctl.get("calibration_file_by_pattern", {}).get(args.pattern, ctl["calibration_file"])
    capacity_model = CapacityModel.load(
        REPO_ROOT / calibration_file,
        buffer_percent=cfg["aws"]["pc_buffer_percent"],
        max_concurrency=ctl["max_provisioned_concurrency"],
    )
    print(f"Capacity model: {calibration_file} ({capacity_model.margin_label()}, "
          f"cap {capacity_model.max_concurrency})")
    logging.getLogger("cmdstanpy").disabled = True
    np.random.seed(cfg["forecasting"]["rolling"]["random_seed"])

    mode = "replay" if args.replay else ("apply" if args.apply else "dryrun")
    run_name = args.run_name or f"{datetime.now():%Y%m%d-%H%M}_{args.condition}_{args.pattern}_{mode}"
    log = DecisionLog(RESULTS_DIR / f"{run_name}.csv")
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
