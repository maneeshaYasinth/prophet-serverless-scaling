"""
Run this locally to see exactly what Prophet's input and output look like, with no
AWS/Lambda dependency. Use it to build intuition before deciding what modifications
(regressors, confidence-bound triggers, etc.) you actually need.

Usage: python explore_prophet.py
"""

import pandas as pd
import matplotlib.pyplot as plt
from prophet import Prophet

from synthetic_traffic import generate_steady, generate_spiky, generate_seasonal


def explore(pattern_name: str, df: pd.DataFrame, forecast_periods: int = 60):
    print(f"\n{'=' * 60}")
    print(f"PATTERN: {pattern_name}")
    print(f"{'=' * 60}")

    # ---- INPUT ----
    # Prophet requires exactly two columns to start: ds (datetime) and y (the value
    # you're forecasting). That's it for vanilla Prophet -- no other columns needed.
    print("\n--- INPUT to Prophet (df.head()) ---")
    print(df.head())
    print(f"\nInput shape: {df.shape}")
    print(f"Input dtypes:\n{df.dtypes}")

    # ---- FIT ----
    model = Prophet(interval_width=0.95)
    model.fit(df)

    # ---- FORECAST ----
    # make_future_dataframe extends the input timeline forward by `periods` steps,
    # at the same frequency Prophet inferred from your input ds column.
    future = model.make_future_dataframe(periods=forecast_periods, freq="5min")
    forecast = model.predict(future)

    # ---- OUTPUT ----
    # predict() returns MANY columns (trend, weekly, yearly, seasonalities, etc.) --
    # these are the ones that actually matter for your scaling decision:
    print("\n--- OUTPUT from Prophet (forecast columns that matter) ---")
    output_cols = ["ds", "yhat", "yhat_lower", "yhat_upper"]
    print(forecast[output_cols].tail(forecast_periods).head(10))
    print(f"\nFull forecast dataframe has {len(forecast.columns)} columns total: {list(forecast.columns)}")

    # ---- THE KEY PROBLEM THIS ILLUSTRATES ----
    # Check how often yhat_lower goes negative -- this is meaningless for a traffic
    # count (can't have negative requests) and is exactly what motivates clipping
    # yhat_upper at 0 and scaling to yhat_upper instead of yhat.
    future_only = forecast.tail(forecast_periods)
    negative_lower_pct = (future_only["yhat_lower"] < 0).mean() * 100
    print(f"\n% of forecasted yhat_lower values that are negative: {negative_lower_pct:.1f}%")
    print("(Negative lower bounds don't make sense for a traffic count -- vanilla")
    print(" Prophet doesn't know y can't go below 0 unless you tell it to.)")

    # ---- PLOT ----
    fig = model.plot(forecast)
    plt.title(f"{pattern_name} traffic: Prophet forecast")
    plt.xlabel("time")
    plt.ylabel("requests")
    fig.savefig(f"results/{pattern_name}_forecast.png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"\nPlot saved to results/{pattern_name}_forecast.png")

    return forecast


if __name__ == "__main__":
    import os
    os.makedirs("results", exist_ok=True)
    os.makedirs("data/processed", exist_ok=True)

    explore("steady", generate_steady())
    explore("spiky", generate_spiky())
    explore("seasonal", generate_seasonal())
