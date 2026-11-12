"""
Live forecast -> Provisioned Concurrency loop (C2, C3 Layer 2, C3 Layers 2 + 3, full C3).

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

Layer 3 (condition c3-layer23): each minute the newest complete CloudWatch
minute is compared with a forecast for it from a model that had not seen it
(the window one minute earlier). If that residual is more than
zscore_anomaly_threshold standard deviations above the recent residuals
(Layer3), demand is beyond what the forecast expects, so the targets are raised
to at least what the observed minute needs. It lasts while that minute is
flagged. Downward anomalies are logged but never lower PC: a lower costs little
to skip and an under-provisioned minute costs cold starts. The override can
only be usable about cloudwatch_delay + pc_ready + 1 minutes after a burst
begins (Run 2026-11-06-2), so it cannot catch a burst shorter than that.

Layer 1 (condition c3): CloudWatch signals (forecasting.layer1_regressors) enter
Prophet as extra regressors, lagged by regressor_lag_minutes. Prophet needs a
regressor's value for each forecast minute, and those minutes have no data
yet; with a lag of at least steps_ahead, the value for every forecast minute
was already measured. Plain Prophet has only trend and seasonality, so this
gives it the recent load level.

Layer 4 (condition c3): every condition refits each minute on a sliding window,
so Layer 4 adapts the window's length (Layer4). When the median of the newest
drift_check_minutes residuals sits more than drift_threshold normal-error stds
from the mean, the forecast has been biased for most of those minutes: traffic
has changed. The window then restarts just before the change (at least
adaptive_min_window_minutes) and grows back to training_window_minutes.
Two variants (forecasting.layer4_variants): v1 as run in 2026-11-10-2 / -3 (all
residuals, both directions); v2 for c3v2 (Analysis 2026-11-12-1) leaves out the
minutes Layer 3 flags, because a spike is not a level shift, and restarts only on
upward drift (under-forecasting). On spiky traffic v1 restarted on spike residuals
and on the over-forecast after a spike cluster; each restart forgot the earlier
spikes, the yhat_upper band narrowed and PC fell to 38 before the spike at 131.
An over-forecast costs money, not cold starts, so v2 leaves it to the sliding window,
the same asymmetry as Layer 3.

Layer 5 (condition c3v2): stabilised scale-down. PC is lowered only to the highest
target of the last scale_down_stabilization_minutes decisions, and only when that
is at least scale_down_min_step_fraction below the configured value. In the spiky
runs the controller trimmed PC by 3-5 environments about every other minute, and
every spike that met spare PC but still had on-demand cold starts came within about
a minute of such a trim (Analysis 2026-11-12-1, hypothesis). This is the
scale-down stabilisation window that Kubernetes' HPA uses. Raises are unchanged.

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
    python -m src.controller.live_controller --condition c3 --pattern spiky \
        --replay data/processed/spiky_c1_ec2_run2.csv --layers 123     # replay ablation
"""

import argparse
import csv
import logging
import signal
import statistics
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yaml

from src.controller.capacity_model import CapacityModel
from src.evaluation.rolling_forecast import CONFIG_PATH, REPO_ROOT
from src.forecasting.anomaly_detector import ZScoreAnomalyDetector
from src.forecasting.prophet_baseline import fit_vanilla_prophet

RESULTS_DIR = REPO_ROOT / "results" / "controller"
# Enhancement layers each condition uses (C2 = none). Layer 2 = scale to yhat_upper
# Layer 5 = stabilised scale-down. c3v2 = C3 after Analysis 2026-11-12-1 (Layer 4 v2 + Layer 5)
CONDITION_LAYERS = {"c2": "", "c3-layer2": "2", "c3-layer23": "23", "c3": "1234", "c3v2": "12345"}
CONDITION_LAYER4 = {"c3v2": "v2"}  # every other condition with Layer 4 uses v1
TICK_OFFSET_S = 5  # decide a few seconds after each minute boundary


def plan(history: pd.DataFrame, now: pd.Timestamp, cfg: dict, capacity_model: CapacityModel,
         field: str, pattern: str, history_start: pd.Timestamp | None = None,
         residual: bool = False, regressors: tuple[str, ...] = (),
         window: int | None = None, prev_window: int | None = None) -> dict:
    """
    One decision. Pure: no AWS, no clock. `history` has ds (tz-naive UTC
    minute starts) and y; only rows with ds < now - cloudwatch_delay are used,
    so nothing the controller could not have seen at `now` leaks in.

    history_start drops earlier rows. Without it, an earlier session inside the
    fetch lookback (plus the zero-filled gap after it) enters the training
    window: Run 2026-10-16-2's first 10 decisions trained on a smoke test from
    30 minutes before and were off by up to 40%.

    residual=True (Layer 3) also forecasts the newest complete minute from the
    window one minute earlier, which had not seen it: residual_y, residual_yhat.

    regressors (Layer 1): history columns added to Prophet lagged by
    regressor_lag_minutes, looked up only in data already seen. window (Layer 4)
    overrides training_window_minutes; prev_window is the length the decision
    one minute earlier used, so the residual comes from exactly that model.
    """
    ctl, fc = cfg["controller"], cfg["forecasting"]
    roll = fc["rolling"]
    window = window or roll["training_window_minutes"]
    prev_window = prev_window or window
    step = roll["step_minutes"]
    data_end = now - pd.Timedelta(minutes=ctl["cloudwatch_delay_minutes"])
    if history_start is not None:
        history = history[history.ds >= history_start]
    seen = history[history.ds < data_end]
    lag = fc["regressor_lag_minutes"] if regressors else 0
    reg_cols = [f"{c}_lag{lag}" for c in regressors]
    seen = add_lagged(seen, seen, regressors, lag)
    train = seen.tail(window)

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
    if regressors and lag < steps_ahead:
        raise ValueError(f"regressor_lag_minutes {lag} < steps_ahead {steps_ahead}: the forecast "
                         f"minutes' regressor values would not be measured yet")
    horizon = add_lagged(horizon, seen, regressors, lag)

    def fit(frame):
        # The first `lag` minutes after history_start have no lagged value; they are left out
        return fit_vanilla_prophet(
            frame[["ds", "y", *reg_cols]].dropna(),
            interval_width=fc["confidence_interval"],
            seasonality_period_minutes=cfg["traffic_patterns"][pattern].get("period_minutes"),
            fourier_order=roll["fourier_order"],
            regressors=tuple(reg_cols),
        )

    fcst = fit(train).predict(horizon[["ds", *reg_cols]])
    short = fcst.iloc[:step + 1]
    if residual and len(seen) > prev_window:
        prev = seen.iloc[-prev_window - 1:-1]  # exactly the window of the decision one minute earlier
        newest = seen.iloc[[-1]]
        row.update(residual_ds=newest.ds.iloc[0], residual_y=float(newest.y.iloc[0]),
                   residual_yhat=round(float(fit(prev).predict(newest[["ds", *reg_cols]]).yhat.iloc[0]), 1))
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


def add_lagged(frame: pd.DataFrame, seen: pd.DataFrame, columns, lag: int) -> pd.DataFrame:
    """Layer 1: adds <col>_lag<lag> = seen's col at ds - lag minutes. Values come only from
    `seen` (data the controller had at decision time), so a lag shorter than the forecast
    reach gives NaN rather than leaking future data; plan() rejects that case."""
    if not columns:
        return frame
    frame = frame.copy()
    src = seen.set_index("ds")
    for col in columns:
        shifted = pd.Series(src[col].values, index=src.index + pd.Timedelta(minutes=lag))
        frame[f"{col}_lag{lag}"] = frame.ds.map(shifted)
    return frame


def decide(target, target_up, configured: int, pc_status: str, usable: int,
           policy: str, min_lower_fraction: float = 0.0) -> tuple[int, str | None]:
    """
    The scaling rule. Pure. Returns (PC to configure, action), action one of
    raise / lower / keep / held (a change wanted, but a put would restart the
    allocation still IN_PROGRESS), damped (a lower smaller than
    min_lower_fraction of configured, skipped; Layer 5), or set (every_minute
    policy); None when there is no target yet. usable = environments already allocated.
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
        if configured - target < min_lower_fraction * configured:
            return configured, "damped"
        return target, "lower"
    return configured, "keep"


class Layer3:
    """
    Z-score residual override, applied to a plan() row (condition c3-layer23).
    Each complete minute is scored once, even if CloudWatch is late and the same
    minute is newest for two ticks.
    """

    def __init__(self, cfg: dict, capacity_model: CapacityModel, override: bool = True):
        fc = cfg["forecasting"]
        self.detector = ZScoreAnomalyDetector(window_size=fc["zscore_window_minutes"],
                                              z_threshold=fc["zscore_anomaly_threshold"],
                                              min_residuals=fc["zscore_min_residuals"],
                                              exclude_anomalies=True)
        self.capacity_model = capacity_model
        self.override = override  # False: residuals scored for Layer 4 only, targets untouched
        self.last_ds = None

    def apply(self, d: dict) -> dict:
        if d.get("status") != "ok" or d.get("residual_yhat") is None or d["residual_ds"] == self.last_ds:
            return d
        self.last_ds = d["residual_ds"]
        r = self.detector.update_and_check(d["residual_y"], d["residual_yhat"])
        d["z_score"], d["anomaly"] = round(r["z_score"], 2), r["is_anomaly"]
        if self.override and r["is_anomaly"] and r["z_score"] > 0:
            # The forecast is missing demand that is already here: provision at least for it
            d["override_target"] = self.capacity_model.target(d["residual_y"])
            d["target"] = max(d["target"], d["override_target"])
            d["target_up"] = max(d["target_up"], d["override_target"])
        return d


class Layer4:
    """
    Adaptive training window. Reads the residuals Layer 3 scores (and its spread of
    normal error, which leaves spikes out). The median of the newest
    drift_check_minutes residuals ignores a few spike minutes but moves when the
    forecast is off in the same direction for most of them, i.e. the level or shape of
    traffic changed. Then minutes before the change mislead the fit, so the window
    restarts at the oldest of those residuals and grows back by one minute per minute.
    """

    def __init__(self, cfg: dict, layer3: Layer3, variant: str = "v1"):
        fc = cfg["forecasting"]
        v = fc["layer4_variants"][variant]
        self.variant = variant
        self.exclude_anomalies = v["exclude_anomalies"]
        self.directions = {"both": (1, -1), "up": (1,)}[v["direction"]]
        self.long = fc["rolling"]["training_window_minutes"]
        self.shortest = fc["adaptive_min_window_minutes"]
        self.threshold = fc["drift_threshold"]
        self.newest_lag = pd.Timedelta(minutes=cfg["controller"]["cloudwatch_delay_minutes"] + 1)
        self.detector = layer3.detector
        self.recent = deque(maxlen=fc["drift_check_minutes"])
        self.change_start = None
        self.prev = None  # window of the previous decision, for plan(prev_window=)

    def window(self, now: pd.Timestamp) -> int:
        if self.change_start is None:
            return self.long
        span = int((now - self.newest_lag - self.change_start) / pd.Timedelta(minutes=1)) + 1
        if span >= self.long:
            self.change_start = None
            return self.long
        return max(self.shortest, span)

    def update(self, d: dict) -> dict:
        """Call after Layer3.apply; acts only on a minute Layer 3 scored this tick."""
        if d.get("z_score") is None:
            return d
        if self.exclude_anomalies and d.get("anomaly"):
            return d  # v2: a minute Layer 3 flags is a burst, not evidence of a level shift
        self.recent.append((d["residual_ds"], d["residual_y"] - d["residual_yhat"]))
        spread = self.detector.normal_spread()
        if len(self.recent) < self.recent.maxlen or spread is None or spread[1] == 0:
            return d
        score = (statistics.median(r for _, r in self.recent) - spread[0]) / spread[1]
        d["drift_score"] = round(score, 2)
        if any(sign * score > self.threshold for sign in self.directions):
            self.change_start = pd.Timestamp(self.recent[0][0])
            d["window_restart"] = self.change_start
            self.recent.clear()  # the next check needs residuals from after the restart
        return d


class Layer5:
    """
    Stabilised scale-down: the target a lower may go to is the highest target of the
    last scale_down_stabilization_minutes decisions (this one included), so PC follows a
    falling forecast only once it has stayed down. decide() then skips lowers smaller
    than scale_down_min_step_fraction of the configured PC. Raises use target_up and
    are not touched.
    """

    def __init__(self, cfg: dict):
        ctl = cfg["controller"]
        self.recent = deque(maxlen=ctl["scale_down_stabilization_minutes"])
        self.min_lower_fraction = ctl["scale_down_min_step_fraction"]

    def apply(self, d: dict) -> dict:
        if d.get("target") is None:
            return d
        self.recent.append(d["target"])
        d["target_forecast"] = d["target"]
        d["target"] = max(self.recent)
        return d


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
          "steps_ahead", "yhat_max", "yhat_upper_max", "residual_ds", "residual_y", "residual_yhat",
          "z_score", "anomaly", "override_target", "drift_score", "window_restart", "target_forecast", "target", "target_up", "pc_status",
          "pc_allocated", "action", "configured", "applied", "actual_concurrency", "error"]


class Layers:
    """The enhancement layers a run uses, applied around each plan() call."""

    def __init__(self, layers: str, cfg: dict, capacity_model: CapacityModel, layer4_variant: str = "v1"):
        self.field = "yhat_upper" if "2" in layers else "yhat"
        self.regressors = tuple(cfg["forecasting"]["layer1_regressors"]) if "1" in layers else ()
        # Layer 4 needs Layer 3's residuals even when the override itself is off
        self.layer3 = (Layer3(cfg, capacity_model, override="3" in layers)
                       if "3" in layers or "4" in layers else None)
        self.layer4 = Layer4(cfg, self.layer3, layer4_variant) if "4" in layers else None
        self.layer5 = Layer5(cfg) if "5" in layers else None
        self.min_lower_fraction = self.layer5.min_lower_fraction if self.layer5 else 0.0

    def plan(self, history, now, cfg, capacity_model, pattern, history_start=None) -> dict:
        window = self.layer4.window(now) if self.layer4 else None
        d = plan(history, now, cfg, capacity_model, self.field, pattern, history_start,
                 residual=self.layer3 is not None, regressors=self.regressors,
                 window=window, prev_window=self.layer4.prev if self.layer4 else None)
        if self.layer4 and d.get("status") == "ok":
            self.layer4.prev = window
        if self.layer3:
            d = self.layer3.apply(d)
        if self.layer4:
            d = self.layer4.update(d)
        if self.layer5:
            d = self.layer5.apply(d)  # after Layer 3, so an override is held for the window too
        return d


def run_replay(args, cfg, capacity_model, layers, log):
    history = pd.read_csv(args.replay, parse_dates=["ds"])
    ctl = cfg["controller"]
    step = pd.Timedelta(minutes=cfg["forecasting"]["rolling"]["step_minutes"])
    pc, configured = SimulatedPC(ctl["pc_ready_minutes"]), 0
    actual = history.set_index("ds").concurrency if "concurrency" in history else None
    now, rows = history.ds.min(), []
    while now <= history.ds.max():
        d = layers.plan(history, now, cfg, capacity_model, args.pattern)
        d["pc_status"], d["pc_allocated"] = pc.state(now)  # usable this minute
        configured, d["action"] = decide(d.get("target"), d.get("target_up"), configured,
                                         d["pc_status"], d["pc_allocated"], ctl["scale_up_policy"],
                                         layers.min_lower_fraction)
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
    if layers.layer3:
        print(f"layer 3: {int(df.get('anomaly', pd.Series(dtype=bool)).eq(True).sum())} flagged minutes, "
              f"{int(df.get('override_target', pd.Series(dtype=float)).notna().sum())} overrides")
    if layers.layer4:
        restarts = df.get("window_restart", pd.Series(dtype=object)).dropna()
        ok = df[df.status == "ok"]
        print(f"layer 4: {len(restarts)} window restarts {[f'{t:%H:%M}' for t in restarts]}, "
              f"{int((ok.n_train < cfg['forecasting']['rolling']['training_window_minutes']).sum())} "
              f"decisions on a shortened window")
    # Score every minute from the first one PC could be usable until the data ends
    first = df[df.status == "ok"].covers_from.min()
    scored = df[(df.now >= first)].dropna(subset=["actual_concurrency"])
    if len(scored):
        gap = scored.pc_allocated - scored.actual_concurrency
        print(f"minutes with usable PC below measured concurrency: {int((gap < 0).sum())}/{len(scored)}   "
              f"shortfall {(-gap).clip(lower=0).sum():.0f} env-min   "
              f"configured {scored.configured.sum():.0f} env-min   usable range {scored.pc_allocated.min()}-{scored.pc_allocated.max()}")


def run_live(args, cfg, capacity_model, layers, log):
    import boto3
    from botocore.exceptions import ClientError

    from src.controller.provisioned_concurrency import set_provisioned_concurrency
    from src.data_generation.cloudwatch_fetch import fetch

    aws, ctl = cfg["aws"], cfg["controller"]
    fn, alias, region = aws["function_name"], aws["alias"], aws["region"]
    lam = boto3.client("lambda", region_name=region)
    lookback = (cfg["forecasting"]["rolling"]["training_window_minutes"] + ctl["cloudwatch_delay_minutes"] + 5
                + (cfg["forecasting"]["regressor_lag_minutes"] if layers.regressors else 0))
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
                row = layers.plan(history, now, cfg, capacity_model, args.pattern, args.history_start)
            except SystemExit as e:  # fetch() exits when CloudWatch has no datapoints yet
                row.update(status="no_data", error=str(e))

            row["pc_status"], row["pc_allocated"] = read_pc(lam, fn, alias) if args.apply else sim.state(now)
            new, row["action"] = decide(row.get("target"), row.get("target_up"), configured,
                                        row["pc_status"], row["pc_allocated"], ctl["scale_up_policy"],
                                        layers.min_lower_fraction)
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
                  f"configured={configured}  pc={row.get('pc_status')}:{row.get('pc_allocated')}  "
                  f"{'z=' + str(row['z_score']) if row.get('z_score') is not None else ''}"
                  f"{' OVERRIDE ' + str(row['override_target']) if row.get('override_target') else ''}"
                  f"{' RESTART window from ' + format(row['window_restart'], '%H:%M') if row.get('window_restart') else ''}  "
                  f"{row.get('error') or ''}")

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
    p.add_argument("--condition", choices=sorted(CONDITION_LAYERS), default="c2")
    p.add_argument("--pattern", default="seasonal", help="traffic_patterns key in the config")
    p.add_argument("--replay", help="CloudWatch CSV to replay with a simulated clock (no AWS calls)")
    p.add_argument("--minutes", type=int, default=90, help="live run length")
    p.add_argument("--apply", action="store_true", help="actually set Provisioned Concurrency")
    p.add_argument("--policy", choices=["wait_for_ready", "every_minute"],
                   help="override controller.scale_up_policy (e.g. to replay the old behaviour)")
    p.add_argument("--run-name", help="decision log file name (default: timestamp_condition_pattern_mode)")
    p.add_argument("--layers", help="replay only: override the condition's layers, e.g. 123 "
                   "(layer-by-layer ablation on the same data)")
    p.add_argument("--layer4", choices=["v1", "v2"],
                   help="replay only: override the condition's Layer 4 variant")
    p.add_argument("--history-start", type=pd.Timestamp,
                   help="UTC minute (e.g. 2026-10-16T19:08); ignore CloudWatch data before it")
    args = p.parse_args()
    if args.apply and args.replay:
        p.error("--apply cannot be combined with --replay")
    if args.layers is not None and (not args.replay or set(args.layers) - set("12345")):
        p.error("--layers takes digits 1-5 and works only with --replay")
    if args.layer4 is not None and not args.replay:
        p.error("--layer4 works only with --replay")

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
    layer_set = CONDITION_LAYERS[args.condition] if args.layers is None else args.layers
    layer4_variant = args.layer4 or CONDITION_LAYER4.get(args.condition, "v1")
    print(f"Layers: {', '.join(layer_set) or 'none (vanilla Prophet)'}"
          f"{f' (Layer 4 {layer4_variant})' if '4' in layer_set else ''}")
    layers = Layers(layer_set, cfg, capacity_model, layer4_variant)
    try:
        if args.replay:
            run_replay(args, cfg, capacity_model, layers, log)
        else:
            run_live(args, cfg, capacity_model, layers, log)
    finally:
        log.close()
        print(f"Decisions saved to {log.path}")


if __name__ == "__main__":
    main()
