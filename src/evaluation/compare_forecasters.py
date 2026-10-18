"""
Prophet vs the seasonal-naive benchmark on the same walk-forward forecasts.

Reads results/rolling_forecast/<name>_forecasts.csv (Prophet) and
<name>_snaive_forecasts.csv, which share origins, horizons and actuals, and reports:
- MAE, MAPE, 95%-band coverage and band width per model
- skill = 1 - MAE_prophet / MAE_snaive  (> 0: Prophet better; 0.2 = 20% less error)
- share of individual forecasts where Prophet's error is smaller (paired)

Usage (after running rolling_forecast with --model prophet and --model snaive):
    python -m src.evaluation.compare_forecasters seasonal_c2dry_ec2_run1
"""

import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.evaluation.rolling_forecast import ACTUAL_COLOR, INK_SECONDARY, RESULTS_DIR, _style

NAIVE_COLOR = "#a3a29c"  # quiet grey: the benchmark, not the subject


def load(name: str, suffix: str) -> pd.DataFrame:
    df = pd.read_csv(RESULTS_DIR / f"{name}{suffix}_forecasts.csv", parse_dates=["origin", "ds"])
    return df.assign(
        abs_err=(df.y - df.yhat).abs(),
        covered=(df.y >= df.yhat_lower) & (df.y <= df.yhat_upper),
        band=df.yhat_upper - df.yhat_lower,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("name", help="data file stem, e.g. seasonal_c2dry_ec2_run1")
    args = p.parse_args()

    prophet, naive = load(args.name, ""), load(args.name, "_snaive")
    paired = prophet.merge(naive, on=["origin", "h"], suffixes=("_p", "_n"))
    if len(paired) != len(prophet):
        raise SystemExit("forecast files do not cover the same origins and horizons")

    rows = []
    for label, df in [("prophet", prophet), ("seasonal_naive", naive)]:
        rows.append({
            "model": label,
            "forecasts": len(df),
            "mae": round(df.abs_err.mean(), 1),
            "mape_pct": round((df.abs_err / df.y).mean() * 100, 2),
            "coverage_pct": round(df.covered.mean() * 100, 1),
            "mean_band_width": round(df.band.mean(), 1),
        })
    table = pd.DataFrame(rows).set_index("model")
    skill = 1 - prophet.abs_err.mean() / naive.abs_err.mean()
    wins = (paired.abs_err_p < paired.abs_err_n).mean()

    by_h = pd.DataFrame({"prophet": prophet.groupby("h").abs_err.mean(),
                         "seasonal_naive": naive.groupby("h").abs_err.mean()})
    out = RESULTS_DIR / f"{args.name}_comparison"
    table.to_csv(f"{out}.csv")
    by_h.round(2).to_csv(f"{out}_by_horizon.csv")

    fig, ax = plt.subplots(figsize=(8, 4), constrained_layout=True)
    ax.plot(by_h.index, by_h.seasonal_naive, color=NAIVE_COLOR, linewidth=2, marker="o", markersize=5,
            label="Seasonal naive (same minute, one cycle ago)")
    ax.plot(by_h.index, by_h.prophet, color=ACTUAL_COLOR, linewidth=2, marker="o", markersize=5, label="Prophet")
    ax.set_ylim(bottom=0)
    ax.set_xticks(by_h.index)
    ax.set_xlabel("Forecast horizon (minutes ahead)")
    ax.set_ylabel("Mean absolute error (invocations per minute)")
    ratio = naive.abs_err.mean() / prophet.abs_err.mean()
    finding = (f"Prophet has {skill:.0%} less error than seasonal naive" if skill > 0
               else f"Seasonal naive has {1 / ratio:.1f}x less error than Prophet")
    ax.set_title(f"{finding}; Prophet closer in {wins:.0%} of forecasts", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    _style(ax)
    fig.savefig(f"{out}.png", dpi=200)
    plt.close(fig)

    print(table.to_string())
    print(f"skill (1 - MAE_prophet/MAE_snaive): {skill:+.3f}   Prophet closer in {wins:.0%} of {len(paired)} paired forecasts")
    print(f"Saved {out}.csv, _by_horizon.csv, .png")


if __name__ == "__main__":
    main()
