"""
Fit the forecast -> Provisioned Concurrency model (CapacityModel) from a
warm-up run's CloudWatch data, then replay the rolling-forecast output to see
how much capacity C2 (scale to yhat) and C3 Layer 2 (scale to yhat_upper)
would have requested against the concurrency actually observed.

Usage (from the repo root, after src.evaluation.rolling_forecast):
    python -m src.evaluation.calibrate_capacity data/processed/seasonal_train_run1.csv
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from src.controller.capacity_model import CapacityModel
from src.evaluation.rolling_forecast import ACTUAL_COLOR, CONFIG_PATH, FORECAST_COLOR, INK_SECONDARY, REPO_ROOT, _style

RESULTS_DIR = REPO_ROOT / "results" / "capacity_calibration"
FORECASTS_DIR = REPO_ROOT / "results" / "rolling_forecast"
UPPER_COLOR = "#1baf7a"  # categorical slot 3 of the dataviz reference palette


def provisioning_stats(target: pd.Series, actual: pd.Series) -> dict:
    """Under-provisioned minutes risk cold starts; excess env-minutes cost money."""
    gap = target - actual
    return {
        "minutes": int(len(gap)),
        "under_provisioned_minutes": int((gap < 0).sum()),
        "under_provisioned_pct": round(float((gap < 0).mean() * 100), 1),
        "mean_shortfall_when_under": round(float(-gap[gap < 0].mean()), 2) if (gap < 0).any() else 0.0,
        "provisioned_env_minutes": int(target.sum()),
        "excess_env_minutes": int(gap.clip(lower=0).sum()),
    }


def plot(df, model, replay, out_path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [1, 1.6]},
                                   constrained_layout=True)

    # (a) calibration: measured concurrency vs request rate
    rate = df.y / model.interval_seconds
    xs = np.linspace(rate.min(), rate.max(), 50)
    fit = model.intercept + model.slope_per_rps * xs
    ax1.scatter(rate, df.concurrency, s=22, color=ACTUAL_COLOR, edgecolor="white", linewidth=0.8,
                label="Observed minute", zorder=3)
    ax1.plot(xs, fit, color=INK_SECONDARY, linewidth=2, label="Least-squares fit")
    ax1.plot(xs, fit + model.headroom, color=FORECAST_COLOR, linewidth=2, linestyle="--",
             label=f"Fit + headroom ({model.headroom:.1f})")
    ax1.set_xlabel("Request rate (requests per second)")
    ax1.set_ylabel("Peak concurrent executions per minute")
    ax1.set_title("(a) Concurrency vs request rate", loc="left", fontsize=11)
    ax1.legend(frameon=False, fontsize=9, loc="upper left")
    _style(ax1)

    # (b) replay: what each condition would have provisioned
    ax2.step(replay.ds, replay.concurrency, where="mid", color=ACTUAL_COLOR, linewidth=2, label="Actual concurrency")
    ax2.step(replay.ds, replay.target_c2, where="mid", color=FORECAST_COLOR, linewidth=2, label="C2 target (yhat)")
    ax2.step(replay.ds, replay.target_c3, where="mid", color=UPPER_COLOR, linewidth=2, label="C3 target (yhat_upper)")
    ax2.set_xlabel("Time (UTC)")
    ax2.set_ylabel("Concurrent executions")
    ax2.set_title("(b) Provisioned target vs actual, 10-min-ahead forecasts", loc="left", fontsize=11)
    ax2.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    ax2.set_ylim(bottom=0)
    ax2.legend(frameon=False, fontsize=9, loc="lower left")
    _style(ax2)

    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("data", help="CSV with ds, y, concurrency (1-minute steps)")
    args = p.parse_args()

    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    horizon = cfg["forecasting"]["lead_time_minutes"]
    df = pd.read_csv(args.data, parse_dates=["ds"])
    name = Path(args.data).stem

    model = CapacityModel.fit(df, quantile=cfg["capacity"]["calibration_quantile"],
                              buffer_percent=cfg["aws"]["pc_buffer_percent"])
    rate = df.y / model.interval_seconds
    residuals = df.concurrency - (model.intercept + model.slope_per_rps * rate)
    r2 = 1 - residuals.var() / df.concurrency.var()

    forecasts = pd.read_csv(FORECASTS_DIR / f"{name}_forecasts.csv", parse_dates=["origin", "ds"])
    replay = forecasts[forecasts.h == horizon].merge(df[["ds", "concurrency"]], on="ds")
    replay["target_c2"] = replay.yhat.map(model.target)
    replay["target_c3"] = replay.yhat_upper.map(model.target)
    replay["target_actual_rate"] = replay.y.map(model.target)  # perfect-forecast reference

    stats = {
        "c2_yhat": provisioning_stats(replay.target_c2, replay.concurrency),
        "c3_yhat_upper": provisioning_stats(replay.target_c3, replay.concurrency),
        "perfect_forecast": provisioning_stats(replay.target_actual_rate, replay.concurrency),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    model.save(RESULTS_DIR / f"{name}.json", source=args.data, r_squared=round(float(r2), 3),
               calibration_quantile=cfg["capacity"]["calibration_quantile"], horizon_minutes=horizon,
               replay=stats, note="replay is in-sample: calibrated and evaluated on the same run")
    replay.to_csv(RESULTS_DIR / f"{name}_replay.csv", index=False)
    plot(df, model, replay, RESULTS_DIR / f"{name}_calibration.png")

    print(f"concurrency = {model.intercept:.2f} + {model.slope_per_rps:.4f} x rps   "
          f"(R^2 {r2:.3f}, headroom {model.headroom:.2f}, buffer {model.buffer_percent:.0f}%)")
    print(pd.DataFrame.from_dict(stats, orient="index").to_string())  # per-column dtypes keep counts as ints
    print(f"Saved to {RESULTS_DIR}/{name}*")


if __name__ == "__main__":
    main()
