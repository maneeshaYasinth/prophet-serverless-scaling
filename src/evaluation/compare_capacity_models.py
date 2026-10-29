"""
Compare capacity-model margins (additive vs multiplicative) across runs, and
save the pooled calibration the controller should use.

Each candidate is scored with a perfect forecast (the actual request rate of
each minute), so only the capacity model is judged, not Prophet:
    - leave-one-run-out: fit on every other run, test on the held-out run
      (the honest out-of-sample check)
    - pooled: fit and test on all runs together (in-sample reference)

Why: the run-1 calibration under-provisioned 16 of 94 minutes of run 2 because
run 2 went beyond its fitted load range (Run 2026-10-18-5, Known issue 7), and
the scatter around the line grows with load, which a constant margin ignores.

Outputs results/capacity_calibration/<name>_comparison.csv and .png, plus
<name>.json: the pooled fit with capacity.headroom_mode from the config, which
controller.calibration_file can point at.

Usage (from the repo root):
    python -m src.evaluation.compare_capacity_models \
        data/processed/seasonal_c2dry_ec2_run1.csv data/processed/seasonal_c2dry_ec2_run2.csv \
        --name ec2_pooled_run1_run2
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
from src.evaluation.calibrate_capacity import RESULTS_DIR, provisioning_stats
from src.evaluation.evaluate_decisions import FIT_RUN_COLOR
from src.evaluation.rolling_forecast import ACTUAL_COLOR, CONFIG_PATH, FORECAST_COLOR, INK_SECONDARY, REPO_ROOT, _style

MODES = ["additive", "multiplicative"]
MODE_COLOR = {"additive": INK_SECONDARY, "multiplicative": FORECAST_COLOR}
RUN_COLORS = [FIT_RUN_COLOR, ACTUAL_COLOR]  # two runs so far; a third gets a new slot, not a cycled one


def short(run_name: str) -> str:
    """seasonal_c2dry_ec2_run2 -> run2, so tick labels and legends stay readable."""
    return run_name.rsplit("_", 1)[-1]


def score(model: CapacityModel, test: pd.DataFrame) -> dict:
    target = test.y.map(model.target)  # perfect forecast: the minute's actual invocations
    stats = provisioning_stats(target, test.concurrency)
    stats["excess_pct_of_actual"] = round(stats["excess_env_minutes"] / test.concurrency.sum() * 100, 1)
    stats["worst_shortfall"] = int(max(0, (test.concurrency - target).max()))
    return stats


def compare(runs: dict, quantile: float, buffer: float) -> pd.DataFrame:
    rows = []
    for mode in MODES:
        for held_out, test in runs.items():
            train = pd.concat([df for name, df in runs.items() if name != held_out])
            model = CapacityModel.fit(train, quantile, buffer, headroom_mode=mode)
            rows.append({"mode": mode, "split": f"test {held_out}", "out_of_sample": True, **score(model, test)})
        pooled = pd.concat(runs.values())
        model = CapacityModel.fit(pooled, quantile, buffer, headroom_mode=mode)
        rows.append({"mode": mode, "split": "pooled", "out_of_sample": False, **score(model, pooled)})
    return pd.DataFrame(rows)


def plot(runs, models, table, quantile, out_path):
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 4.4), gridspec_kw={"width_ratios": [1.2, 1, 1]},
                                        constrained_layout=True)

    # (a) the data and the two pooled margins
    for (name, df), color in zip(runs.items(), RUN_COLORS):
        ax1.scatter(df.y / 60, df.concurrency, s=20, color=color, edgecolor="white", linewidth=0.6,
                    label=short(name), zorder=3)
    xs = np.linspace(0, max(df.y.max() for df in runs.values()) / 60, 100)
    for mode, model in models.items():
        ax1.plot(xs, model.provisioned(xs), color=MODE_COLOR[mode], linewidth=2,
                 linestyle="--" if mode == "additive" else "-", label=f"{mode}: {model.margin_label()}")
    ax1.set_xlabel("Request rate (requests per second)")
    ax1.set_ylabel("Peak concurrent executions per minute")
    ax1.set_title("(a) Pooled fit with each margin", loc="left", fontsize=11)
    ax1.legend(frameon=False, fontsize=9, loc="upper left")
    _style(ax1)

    # (b), (c) under-provisioning and cost for each split, side by side per mode
    splits = list(dict.fromkeys(table.split))
    x = np.arange(len(splits))
    width = 0.38
    for ax, col, title, ylabel in [
        (ax2, "under_provisioned_pct", "(b) Minutes under-provisioned", "Under-provisioned minutes (%)"),
        (ax3, "excess_pct_of_actual", "(c) Spare capacity (cost)", "Excess env-minutes (% of actual)"),
    ]:
        for i, mode in enumerate(MODES):
            vals = table[table["mode"] == mode].set_index("split").loc[splits, col]
            bars = ax.bar(x + (i - 0.5) * (width + 0.02), vals, width, color=MODE_COLOR[mode], label=mode,
                          edgecolor="white", linewidth=1)
            ax.bar_label(bars, fmt="%.1f", fontsize=8, color=INK_SECONDARY, padding=2)
        if col == "under_provisioned_pct":
            ax.axhline((1 - quantile) * 100, color=INK_SECONDARY, linewidth=1, linestyle=":")
            ax.annotate(f"design target {(1 - quantile) * 100:.0f}%", (x[0] - 0.45, (1 - quantile) * 100),
                        xytext=(0, 3), textcoords="offset points", ha="left", fontsize=8, color=INK_SECONDARY)
        ax.set_xticks(x, [f"held out:\n{short(s.removeprefix('test '))}" if s != "pooled" else "pooled\n(in-sample)"
                          for s in splits], fontsize=9)
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc="left", fontsize=11)
        ax.legend(frameon=False, fontsize=9, loc="upper right")
        _style(ax)

    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("data", nargs="+", help="two or more run CSVs with ds, y, concurrency (1-minute steps)")
    p.add_argument("--name", required=True, help="output name under results/capacity_calibration/")
    args = p.parse_args()
    if len(args.data) < 2:
        p.error("need at least two runs for a leave-one-run-out check")

    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    quantile, buffer = cfg["capacity"]["calibration_quantile"], cfg["aws"]["pc_buffer_percent"]
    chosen = cfg["capacity"]["headroom_mode"]
    runs = {Path(f).stem: pd.read_csv(f, parse_dates=["ds"]) for f in args.data}

    table = compare(runs, quantile, buffer)
    pooled = pd.concat(runs.values())
    models = {mode: CapacityModel.fit(pooled, quantile, buffer, headroom_mode=mode) for mode in MODES}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / args.name
    table.to_csv(out.with_name(out.name + "_comparison.csv"), index=False)
    plot(runs, models, table, quantile, out.with_name(out.name + "_comparison.png"))

    model = models[chosen]
    rate = pooled.y / model.interval_seconds
    residuals = pooled.concurrency - (model.intercept + model.slope_per_rps * rate)
    r2 = 1 - residuals.var() / pooled.concurrency.var()
    model.save(out.with_suffix(".json"), sources=[str(Path(f)) for f in args.data],
               load_range_rps=[round(float(rate.min()), 1), round(float(rate.max()), 1)],
               r_squared=round(float(r2), 3), calibration_quantile=quantile,
               comparison=table.to_dict(orient="records"),
               note="pooled fit; comparison scores each margin with a perfect forecast")

    with pd.option_context("display.width", 160):
        print(table[["mode", "split", "under_provisioned_minutes", "minutes", "under_provisioned_pct",
                     "worst_shortfall", "excess_env_minutes", "excess_pct_of_actual"]].to_string(index=False))
    print(f"\npooled {chosen}: concurrency = {model.intercept:.2f} + {model.slope_per_rps:.4f} x rps, "
          f"{model.margin_label()} (R^2 {r2:.3f}, {rate.min():.0f}-{rate.max():.0f} req/s)")
    print(f"Saved {out}.json, {out.name}_comparison.csv, .png")


if __name__ == "__main__":
    main()
