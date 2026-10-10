"""
Rolling-origin (walk-forward) evaluation of vanilla Prophet (condition C2).

Replays a CloudWatch series minute by minute as if each minute were "now":

    at origin t:  fit on [t - W, t)  ->  forecast t+1 .. t+H  ->  compare with actual
    then t += S and repeat

W = forecasting.rolling.training_window_minutes, H = forecasting.lead_time_minutes,
S = forecasting.rolling.step_minutes (configs/experiment_config.yaml). The model
fitted at origin t never sees any row at or after t, so no future data leaks
into training. Only origins with a full H-minute horizon are evaluated.

Usage (from the repo root):
    python -m src.evaluation.rolling_forecast data/processed/seasonal_train_run1.csv
"""

import argparse
import json
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from src.forecasting.prophet_baseline import fit_vanilla_prophet

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "configs" / "experiment_config.yaml"
RESULTS_DIR = REPO_ROOT / "results" / "rolling_forecast"

# Categorical slots 1-2 of the dataviz reference palette (light mode)
ACTUAL_COLOR = "#2a78d6"
FORECAST_COLOR = "#eb6834"
INK_SECONDARY = "#52514e"
GRID_COLOR = "#e4e3df"


def rolling_origin_forecast(
    df: pd.DataFrame,
    window: int,
    horizon: int,
    step: int,
    interval_width: float,
    seasonality_period_minutes: float,
    fourier_order: int,
) -> pd.DataFrame:
    """
    Returns one row per (origin, horizon step) with columns:
    origin, ds, h, y, yhat, yhat_lower, yhat_upper.
    `df` must be a regular 1-minute series with columns ds, y.
    """
    rows = []
    for origin in range(window, len(df) - horizon + 1, step):
        train = df.iloc[origin - window : origin]
        actual = df.iloc[origin : origin + horizon]
        model = fit_vanilla_prophet(
            train,
            interval_width=interval_width,
            seasonality_period_minutes=seasonality_period_minutes,
            fourier_order=fourier_order,
        )
        fcst = model.predict(actual[["ds"]])
        for h, (a, f) in enumerate(zip(actual.itertuples(), fcst.itertuples()), start=1):
            rows.append(
                {
                    "origin": df["ds"].iloc[origin],
                    "ds": a.ds,
                    "h": h,
                    "y": a.y,
                    "yhat": f.yhat,
                    "yhat_lower": f.yhat_lower,
                    "yhat_upper": f.yhat_upper,
                }
            )
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    """Per-horizon error and interval coverage."""
    r = results.assign(
        abs_err=(results.y - results.yhat).abs(),
        covered=(results.y >= results.yhat_lower) & (results.y <= results.yhat_upper),
    )
    return r.groupby("h").agg(
        n=("y", "size"),
        mae=("abs_err", "mean"),
        mape_pct=("abs_err", lambda e: (e / r.loc[e.index, "y"]).mean() * 100),
        coverage_pct=("covered", lambda c: c.mean() * 100),
        mean_band_width=("yhat_upper", lambda u: (u - r.loc[u.index, "yhat_lower"]).mean()),
    )


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_SECONDARY)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9)
    ax.grid(axis="y", color=GRID_COLOR, linewidth=0.8)
    ax.set_axisbelow(True)


def plot(df: pd.DataFrame, results: pd.DataFrame, summary: pd.DataFrame, horizon: int, out_path: Path):
    at_h = results[results.h == horizon]
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [2.4, 1]}, constrained_layout=True
    )

    # (a) actual vs H-minute-ahead forecast
    ax1.fill_between(at_h.ds, at_h.yhat_lower, at_h.yhat_upper, color=FORECAST_COLOR, alpha=0.18, linewidth=0,
                     label="95% interval")
    ax1.plot(df.ds, df.y, color=ACTUAL_COLOR, linewidth=2, label="Actual (CloudWatch)")
    ax1.plot(at_h.ds, at_h.yhat, color=FORECAST_COLOR, linewidth=2, label=f"Forecast, {horizon} min ahead")
    ax1.axvline(at_h.ds.iloc[0], color=INK_SECONDARY, linewidth=1, linestyle="--")
    ax1.text(at_h.ds.iloc[0], ax1.get_ylim()[1], " first forecast", color=INK_SECONDARY, fontsize=9, va="top")
    ax1.set_xlabel("Time (UTC)")
    ax1.set_ylabel("Invocations per minute")
    ax1.set_title("(a) Actual vs forecast", loc="left", fontsize=11)
    ax1.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    ax1.legend(frameon=False, fontsize=9, loc="lower left")
    _style(ax1)

    # (b) error growth with horizon
    ax2.bar(summary.index, summary.mape_pct, width=0.6, color=ACTUAL_COLOR)
    ax2.set_xlabel("Forecast horizon (minutes ahead)")
    ax2.set_ylabel("Mean absolute percentage error (%)")
    ax2.set_title("(b) Error by horizon", loc="left", fontsize=11)
    ax2.set_xticks(summary.index)
    _style(ax2)

    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("data", help="Prophet-ready CSV with ds, y (1-minute steps)")
    p.add_argument("--pattern", default="seasonal", help="traffic_patterns key in the config")
    args = p.parse_args()

    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    fc = cfg["forecasting"]
    roll = fc["rolling"]
    horizon = fc["lead_time_minutes"]
    period = cfg["traffic_patterns"][args.pattern].get("period_minutes")

    logging.getLogger("cmdstanpy").disabled = True  # one INFO pair per fit otherwise
    np.random.seed(roll["random_seed"])  # Prophet's uncertainty sampling uses numpy's global RNG

    df = pd.read_csv(args.data, parse_dates=["ds"])[["ds", "y"]]
    results = rolling_origin_forecast(
        df,
        window=roll["training_window_minutes"],
        horizon=horizon,
        step=roll["step_minutes"],
        interval_width=fc["confidence_interval"],
        seasonality_period_minutes=period,
        fourier_order=roll["fourier_order"],
    )
    if results.empty:
        raise SystemExit("No complete forecast origins: series shorter than window + horizon.")
    summary = summarize(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    name = Path(args.data).stem
    results.to_csv(RESULTS_DIR / f"{name}_forecasts.csv", index=False)
    meta = {
        "data": args.data,
        "pattern": args.pattern,
        "training_window_minutes": roll["training_window_minutes"],
        "horizon_minutes": horizon,
        "step_minutes": roll["step_minutes"],
        "seasonality_period_minutes": period,
        "fourier_order": roll["fourier_order"],
        "interval_width": fc["confidence_interval"],
        "origins": int(results.origin.nunique()),
        "negative_yhat_lower_pct": round(float((results.yhat_lower < 0).mean() * 100), 2),
        "per_horizon": summary.round(3).reset_index().to_dict(orient="records"),
    }
    (RESULTS_DIR / f"{name}_summary.json").write_text(json.dumps(meta, indent=2, default=str))
    plot(df, results, summary, horizon, RESULTS_DIR / f"{name}_forecast.png")

    print(f"{meta['origins']} forecast origins, horizon {horizon} min, window {roll['training_window_minutes']} min")
    print(summary.round(2).to_string())
    print(f"negative yhat_lower: {meta['negative_yhat_lower_pct']}%")
    print(f"Saved to {RESULTS_DIR}/{name}_*")


if __name__ == "__main__":
    main()
