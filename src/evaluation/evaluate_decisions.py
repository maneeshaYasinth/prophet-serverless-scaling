"""
Score a live controller run against what actually happened.

For each decision in the controller log, compare the Provisioned Concurrency
target with the peak concurrency CloudWatch measured in the window that
decision was in charge of ([covers_from, covers_to)). Also checks the capacity
calibration out of sample: the fitted line is applied to a run it was not
fitted on, alongside the run it was fitted on.

Outputs results/controller/<log stem>_evaluation.csv and _evaluation.png.

Usage (from the repo root, after fetching the run's CloudWatch data):
    python -m src.evaluation.evaluate_decisions \
        results/controller/20261018-0750_seasonal_c2_dryrun.csv \
        data/processed/seasonal_c2dry_ec2_run2.csv
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from src.controller.capacity_model import CapacityModel
from src.evaluation.calibrate_capacity import UPPER_COLOR
from src.evaluation.rolling_forecast import ACTUAL_COLOR, CONFIG_PATH, FORECAST_COLOR, INK_SECONDARY, REPO_ROOT, _style

FIT_RUN_COLOR = "#a3a29c"  # quiet grey: the calibration run is the reference


def score_decisions(log: pd.DataFrame, cw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, d in log[log.status == "ok"].iterrows():
        window = cw[(cw.ds >= d.covers_from) & (cw.ds < d.covers_to)]
        if window.empty:  # window runs past the end of the data
            continue
        rows.append({"now": d.now, "covers_from": d.covers_from, "target": d.target,
                     "actual_peak": window.concurrency.max(),
                     "yhat_max": d.yhat_max, "actual_max": window.y.max()})
    scored = pd.DataFrame(rows)
    scored["gap"] = scored.target - scored.actual_peak
    return scored


def plot(fit_df, run_df, model, scored, out_path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [1, 1.6]},
                                   constrained_layout=True)

    # (a) calibration out of sample
    if fit_df is not None:
        ax1.scatter(fit_df.y / model.interval_seconds, fit_df.concurrency, s=18, color=FIT_RUN_COLOR,
                    edgecolor="white", linewidth=0.6, label="Calibration run (fitted)", zorder=2)
    ax1.scatter(run_df.y / model.interval_seconds, run_df.concurrency, s=22, color=ACTUAL_COLOR,
                edgecolor="white", linewidth=0.8, label="This run (not fitted)", zorder=3)
    rate = run_df.y / model.interval_seconds
    xs = np.linspace(0, rate.max(), 50)
    fit = model.intercept + model.slope_per_rps * xs
    ax1.plot(xs, fit, color=INK_SECONDARY, linewidth=2, label="Calibrated fit")
    ax1.plot(xs, model.provisioned(xs), color=FORECAST_COLOR, linewidth=2, linestyle="--",
             label=model.margin_label())
    if fit_df is not None:
        ax1.axvline(fit_df.y.max() / model.interval_seconds, color=INK_SECONDARY, linewidth=1, linestyle=":")
        ax1.annotate("edge of fitted range", (fit_df.y.max() / model.interval_seconds, ax1.get_ylim()[1]),
                     xytext=(-4, -4), textcoords="offset points", ha="right", va="top", fontsize=9,
                     color=INK_SECONDARY)
    ax1.set_xlabel("Request rate (requests per second)")
    ax1.set_ylabel("Peak concurrent executions per minute")
    ax1.set_title("(a) Calibration applied to a new run", loc="left", fontsize=11)
    ax1.legend(frameon=False, fontsize=9, loc="upper left")
    _style(ax1)

    # (b) each live decision vs the concurrency that arrived
    ax2.step(scored.covers_from, scored.actual_peak, where="post", color=ACTUAL_COLOR, linewidth=2,
             label="Actual peak concurrency")
    ax2.step(scored.covers_from, scored.target, where="post", color=UPPER_COLOR, linewidth=2,
             label="Controller target")
    short = scored[scored.gap < 0]
    ax2.scatter(short.covers_from + pd.Timedelta(seconds=30), short.actual_peak, s=36, color=FORECAST_COLOR,
                zorder=4, label=f"Under-provisioned ({len(short)} of {len(scored)})")
    ax2.set_xlabel("Time (UTC)")
    ax2.set_ylabel("Concurrent executions")
    ax2.set_title("(b) Live decisions vs actual", loc="left", fontsize=11)
    ax2.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    ax2.set_ylim(bottom=0)
    ax2.legend(frameon=False, fontsize=9, loc="lower left")
    _style(ax2)

    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("log", help="controller decision log (results/controller/*.csv)")
    p.add_argument("cloudwatch", help="the run's CloudWatch CSV with ds, y, concurrency")
    p.add_argument("--calibration", help="capacity model JSON (default: controller.calibration_file)")
    args = p.parse_args()

    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    calibration = Path(args.calibration or REPO_ROOT / cfg["controller"]["calibration_file"])
    model = CapacityModel.load(calibration)
    source = json.loads(calibration.read_text()).get("source")  # the run it was fitted on
    fit_df = pd.read_csv(REPO_ROOT / source, parse_dates=["ds"]) if source else None

    log = pd.read_csv(args.log, parse_dates=["now", "covers_from", "covers_to"])
    run_df = pd.read_csv(args.cloudwatch, parse_dates=["ds"])
    scored = score_decisions(log, run_df)

    rate = run_df.y / model.interval_seconds
    residuals = run_df.concurrency - (model.intercept + model.slope_per_rps * rate)
    print(f"{len(scored)} scored decisions: {(scored.gap < 0).sum()} under-provisioned "
          f"(shortfalls {sorted(scored.gap[scored.gap < 0].astype(int).tolist())}), "
          f"mean excess {scored.gap.clip(lower=0).mean():.2f}")
    print(f"calibration on this run: residual mean {residuals.mean():+.2f}, "
          f"{(run_df.concurrency > model.provisioned(rate)).mean() * 100:.1f}% of minutes above the margin")

    out = Path(args.log).with_name(Path(args.log).stem + "_evaluation")
    scored.to_csv(out.with_suffix(".csv"), index=False)
    plot(fit_df, run_df, model, scored, out.with_suffix(".png"))
    print(f"Saved {out}.csv, .png")


if __name__ == "__main__":
    main()
