"""
One analysis for every live run: felt cold starts, latency and cost, by period and per
spike, from the run's own files. Replaces the ad-hoc scratch scripts used up to
Run 2026-11-12-3 (same method; reproduces the logged numbers).

Inputs per run (RUN = e.g. 20261112-1408_spiky_c3v3_apply):
    data/raw/RUN.jsonl, data/raw/RUN.meta.json         client log + run metadata
    results/controller/RUN.csv                         decision log (not for C1)
    --cw RUN=data/processed/....csv                    CloudWatch export with pce/spill/pci
                                                       (needed for cost and peak concurrency)
Spike times come from TrafficPatternShape itself (same seed and duration as the run).

Definitions (configs/experiment_config.yaml, evaluation):
    felt cold start   response > felt_cold_start_ms, counted by request start
                      (timestamp - response time)
    periods           warmup_minutes (no PC anywhere) and pc_period_minutes
    cost              requests + on-demand GB-s on the non-PC share + PC duration GB-s on
                      the PC share + PC allocation on allocated PC during the PC period

Usage:
    python -m src.evaluation.run_analysis RUN [RUN ...] [--cw RUN=CSV ...]
Writes results/analysis/RUN.json and prints the tables.
"""

import argparse
import importlib
import json
import os

import numpy as np
import pandas as pd
import yaml

from src.evaluation.rolling_forecast import CONFIG_PATH, REPO_ROOT

OUT_DIR = REPO_ROOT / "results" / "analysis"


def spike_schedule(meta: dict) -> list[tuple[float, float]]:
    """(start_s, end_s) of every spike, from the generator with the run's settings."""
    if meta["pattern"] != "spiky":
        return []
    os.environ.update(TRAFFIC_PATTERN="spiky", DURATION_S=str(meta["minutes"] * 60), SEED=str(meta["seed"]))
    import src.data_generation.traffic_shapes as ts
    ts = importlib.reload(ts)  # class attributes read the environment at import
    return sorted(ts.TrafficPatternShape().spikes)


def load_client(run: str, t0: float) -> pd.DataFrame:
    cols = {"start": [], "rt": [], "cold": [], "init": [], "billed": []}
    errors = 0
    with open(REPO_ROOT / "data" / "raw" / f"{run}.jsonl") as f:
        for line in f:
            r = json.loads(line)
            if r.get("error"):
                errors += 1
                continue
            cols["start"].append(r["timestamp"] - r["response_time_ms"] / 1000 - t0)
            cols["rt"].append(r["response_time_ms"])
            cols["cold"].append(bool(r.get("cold_start")))
            cols["init"].append(r.get("init_type") or "")
            cols["billed"].append(r.get("billed_duration_ms") or 0.0)
    df = pd.DataFrame(cols)
    df.attrs["errors"] = errors
    return df


def period_stats(df: pd.DataFrame, felt_ms: float) -> dict:
    rt = df.rt.to_numpy()
    if not len(rt):
        return {}
    p = np.percentile(rt, [95, 99, 99.9])
    return {"requests": int(len(rt)), "p95_ms": round(p[0], 1), "p99_ms": round(p[1], 1),
            "p999_ms": round(p[2], 1), "felt_cold_starts": int((rt > felt_ms).sum()),
            "on_demand_inits": int((df.cold & (df.init == "on-demand")).sum())}


def analyse(run: str, cw_path: str | None, cfg: dict) -> dict:
    ev = cfg["evaluation"]
    meta = json.loads((REPO_ROOT / "data" / "raw" / f"{run}.meta.json").read_text())
    t0_ts = pd.Timestamp(meta["started_utc"])
    t0, t0_naive = t0_ts.timestamp(), t0_ts.tz_localize(None)
    df = load_client(run, t0)
    felt_ms = ev["felt_cold_start_ms"]
    (w0, w1), (p0, p1) = ev["warmup_minutes"], ev["pc_period_minutes"]
    minute = df.start / 60
    pc_mask = (minute >= p0) & (minute < p1)
    out = {"run": run, "condition": meta["condition"], "pattern": meta["pattern"], "seed": meta["seed"],
           "commit": meta["commit"], "requests": int(len(df)), "errors": df.attrs["errors"],
           "warmup": period_stats(df[(minute >= w0) & (minute < w1)], felt_ms),
           "pc_period": period_stats(df[pc_mask], felt_ms)}

    log_path = REPO_ROOT / "results" / "controller" / f"{run}.csv"
    log = None
    if log_path.exists():
        log = pd.read_csv(log_path, parse_dates=["now"])
        log["m"] = (log.now - t0_naive).dt.total_seconds() / 60
    cw = None
    if cw_path:
        cw = pd.read_csv(cw_path, parse_dates=["ds"])
        cw["m"] = (cw.ds - t0_naive).dt.total_seconds() / 60

    # Per spike
    spikes = spike_schedule(meta)
    before, after = ev["spike_window_s"]
    felt = df[df.rt > felt_ms]
    in_spike = np.zeros(len(df), bool)
    rows, prev_end = [], None
    for s, e in spikes:
        in_spike |= ((df.start >= s) & (df.start < e)).to_numpy()
        row = {"start_min": round(s / 60, 2), "duration_s": round(e - s),
               "gap_min": None if prev_end is None else round((s - prev_end) / 60, 1),
               "felt": int(((felt.start >= s - before) & (felt.start < e + after)).sum())}
        prev_end = e
        if log is not None and (log.m <= s / 60).any():
            d = log[log.m <= s / 60].iloc[-1]
            recent = log[(log.m > s / 60 - 1.5) & (log.m <= s / 60)]
            row.update(pc_allocated=d.pc_allocated, pc_configured=d.configured,
                       lower_just_before=bool((recent.action == "lower").any()))
        if cw is not None:
            mins = cw[(cw.m >= np.floor(s / 60)) & (cw.m < np.ceil(e / 60))]
            row["peak_concurrency"] = None if mins.empty else int(mins.concurrency.max())
        rows.append(row)
    out["spikes"] = rows
    if spikes:
        out["pc_period_inside_spikes"] = period_stats(df[pc_mask & in_spike], felt_ms)
        out["pc_period_outside_spikes"] = period_stats(df[pc_mask & ~in_spike], felt_ms)

    # PC and cost
    pr = ev["pricing"]
    gb_s = df.billed.sum() / 1000 * pr["memory_gb"]
    if log is not None:
        pc = log[(log.m >= p0) & (log.m < p1)]
        out["pc_allocated_mean"] = round(pc.pc_allocated.mean(), 1)
        out["pc_allocated_min"] = int(pc.pc_allocated.min())
        alloc_env_min = pc.pc_allocated.fillna(0).sum()
        out["actions"] = {k: int(v) for k, v in log.action.value_counts().items()}
        if "window_restart" in log:
            out["window_restarts"] = [str(t) for t in log.window_restart.dropna()]
    else:
        alloc_env_min = 0.0
    if cw is not None and "pci" in cw:
        share = cw.pci.sum() / cw.y.sum()
        cwp = cw[(cw.m >= p0) & (cw.m < p1)]
        out["pc_served_share_pc_period"] = round(cwp.pci.sum() / cwp.y.sum(), 3)
        out["spilled_pc_period"] = int(cwp.spill.sum())
    elif log is None:
        share = 0.0  # no PC at all (C1)
    else:
        share = None
    if share is not None:
        alloc_usd = alloc_env_min * 60 * pr["memory_gb"] * pr["pc_allocation_gb_s_usd"]
        total = (len(df) * pr["request_usd"] + gb_s * (1 - share) * pr["on_demand_gb_s_usd"]
                 + gb_s * share * pr["pc_duration_gb_s_usd"] + alloc_usd)
        out["pc_allocation_usd"] = round(alloc_usd, 3)
        out["cost_per_request_usd"] = float(f"{total / len(df):.3e}")
    return out


def show(r: dict):
    print(f"\n== {r['run']} ({r['condition']}, {r['pattern']}, seed {r['seed']}): "
          f"{r['requests']:,} requests, {r['errors']} errors")
    for k in ("warmup", "pc_period", "pc_period_inside_spikes", "pc_period_outside_spikes"):
        if r.get(k):
            print(f"  {k:<26} {r[k]}")
    for k in ("pc_allocated_mean", "pc_allocated_min", "pc_served_share_pc_period", "spilled_pc_period",
              "pc_allocation_usd", "cost_per_request_usd", "actions", "window_restarts"):
        if k in r:
            print(f"  {k:<26} {r[k]}")
    if r["spikes"]:
        print(pd.DataFrame(r["spikes"]).to_string(index=False))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("runs", nargs="+")
    p.add_argument("--cw", action="append", default=[], help="RUN=path of its CloudWatch export")
    args = p.parse_args()
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    cw = dict(x.split("=", 1) for x in args.cw)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for run in args.runs:
        r = analyse(run, cw.get(run), cfg)
        (OUT_DIR / f"{run}.json").write_text(json.dumps(r, indent=2, default=str))
        show(r)


if __name__ == "__main__":
    main()
