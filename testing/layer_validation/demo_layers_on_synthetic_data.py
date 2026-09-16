"""
Demo: Layer 2 (confidence-bound trigger) + Layer 3 (Z-score anomaly
detection) running against synthetic spiky traffic.

This extends the earlier finding (vanilla Prophet's yhat_lower goes
negative under spiky traffic) into an actual working comparison of total
provisioned capacity across three strategies:

    1. Point-forecast scaling      (yhat)               -- what "vanilla"
                                                             point-scaling
                                                             would do
    2. Confidence-bound scaling    (yhat_upper)          -- Layer 2 alone
    3. Enhanced (Layer 2 + 3)      (yhat_upper + z-score override)

Run:
    python testing/layer_validation/demo_layers_on_synthetic_data.py

Requires: prophet, pandas, numpy, matplotlib (same as your existing
explore_prophet.py environment).
"""

import numpy as np
import pandas as pd
from prophet import Prophet
import matplotlib.pyplot as plt

import sys
import os
sys.path.insert(0, str(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))))

from src.forecasting.confidence_bound_trigger import (
    compute_target_concurrency,
    compute_point_forecast_concurrency,
)
from src.controller.scaling_controller import EnhancedScalingController


def generate_spiky_traffic(n_points=500, freq_minutes=5, seed=42):
    """
    Mirrors the spiky pattern from synthetic_traffic.py: a low baseline
    (~10 req/s) with periodic sharp bursts (~80 req/s), which is what
    produced the negative yhat_lower finding.
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-01-01")
    ds = pd.date_range(start, periods=n_points, freq=f"{freq_minutes}min")

    baseline = 10 + rng.normal(0, 1.0, n_points)
    y = baseline.copy()

    # inject bursts every ~40 points, lasting ~6 points
    burst_period = 40
    burst_len = 6
    for i in range(0, n_points, burst_period):
        end = min(i + burst_len, n_points)
        y[i:end] = 80 + rng.normal(0, 3.0, end - i)

    return pd.DataFrame({"ds": ds, "y": np.clip(y, 0, None)})


def main():
    df = generate_spiky_traffic()

    # Fit Prophet on the first 70% of the series (training), forecast the
    # remainder (evaluation) -- a simple holdout split for this demo.
    split = int(len(df) * 0.7)
    train, holdout = df.iloc[:split], df.iloc[split:]

    model = Prophet(interval_width=0.95)
    model.fit(train)

    future = model.make_future_dataframe(periods=len(holdout), freq="5min")
    forecast = model.predict(future)

    # Align forecast rows with the holdout's actual values for evaluation.
    eval_df = holdout.merge(
        forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]], on="ds", how="left"
    ).dropna()

    print(f"Evaluating over {len(eval_df)} holdout points\n")

    # --- Strategy 1: point-forecast scaling (yhat) ---
    point_capacity = [
        compute_point_forecast_concurrency(row, requests_per_instance=10)
        for _, row in eval_df.iterrows()
    ]

    # --- Strategy 2: confidence-bound scaling (yhat_upper) -- Layer 2 alone ---
    bound_capacity = [
        compute_target_concurrency(row, requests_per_instance=10)
        for _, row in eval_df.iterrows()
    ]

    # --- Strategy 3: enhanced (Layer 2 + Layer 3) ---
    controller = EnhancedScalingController(requests_per_instance=10)
    enhanced_capacity = []
    for _, row in eval_df.iterrows():
        decision = controller.decide(row, actual=row["y"])
        enhanced_capacity.append(decision["target_concurrency"])

    # --- Compare total provisioned capacity (proxy for cost) ---
    total_point = sum(point_capacity)
    total_bound = sum(bound_capacity)
    total_enhanced = sum(enhanced_capacity)

    pct_over_bound = 100 * (total_bound - total_point) / total_point
    pct_over_enhanced = 100 * (total_enhanced - total_point) / total_point

    negative_lower_pct = 100 * (eval_df["yhat_lower"] < 0).mean()

    print("=== Results: spiky traffic, holdout period ===")
    print(f"yhat_lower negative for {negative_lower_pct:.1f}% of points")
    print(f"Total capacity, point-forecast (yhat):        {total_point}")
    print(f"Total capacity, confidence-bound (yhat_upper): {total_bound}  ({pct_over_bound:+.1f}% vs point)")
    print(f"Total capacity, enhanced (L2 + L3):             {total_enhanced}  ({pct_over_enhanced:+.1f}% vs point)")

    summary = controller.activation_summary()
    print("\n=== Layer activation summary ===")
    print(summary)

    # --- Plot ---
    # Capacity values above are in "instance count" units (target_concurrency).
    # Convert back to requests/sec-equivalent (x10) so they're directly
    # comparable to the actual traffic line on the same axis -- otherwise
    # the plot visually implies under-provisioning that isn't really there.
    rpi = 10
    point_capacity_req = [c * rpi for c in point_capacity]
    bound_capacity_req = [c * rpi for c in bound_capacity]
    enhanced_capacity_req = [c * rpi for c in enhanced_capacity]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(eval_df["ds"], eval_df["y"], "k.", label="actual traffic", markersize=4)
    ax.step(eval_df["ds"], point_capacity_req, where="post", label="point-forecast capacity (yhat)", color="tab:orange")
    ax.step(eval_df["ds"], bound_capacity_req, where="post", label="confidence-bound capacity (yhat_upper)", color="tab:blue")
    ax.step(eval_df["ds"], enhanced_capacity_req, where="post", label="enhanced capacity (L2+L3)", color="tab:green", linestyle="--")
    ax.set_title("Provisioned capacity under three scaling strategies (spiky traffic)")
    ax.set_xlabel("time")
    ax.set_ylabel("requests/sec (capacity, in traffic-equivalent terms)")
    ax.legend()
    fig.tight_layout()
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    out_path = os.path.join(results_dir, "layer_comparison_spiky.png")
    fig.savefig(out_path, dpi=150)
    print(f"\nPlot saved to {out_path}")


if __name__ == "__main__":
    main()
