import pandas as pd
import matplotlib.pyplot as plt
from prophet import Prophet

from synthetic_traffic import generate_steady, generate_spiky, generate_seasonal


def compute_required_concurrency(forecast_df: pd.DataFrame, buffer_percent: float = 10.0) -> pd.DataFrame:
    """
    Layer 2: confidence-bound scaling trigger. Scales to yhat_upper (clipped at 0,
    since negative concurrency is meaningless) instead of yhat, plus a buffer on top.
    This is the number you'd actually send to put_provisioned_concurrency_config.
    """
    forecast_df = forecast_df.copy()
    forecast_df["required_concurrency_vanilla"] = forecast_df["yhat"].clip(lower=0).round().astype(int)
    forecast_df["required_concurrency_enhanced"] = (
        forecast_df["yhat_upper"].clip(lower=0) * (1 + buffer_percent / 100)
    ).round().astype(int)
    return forecast_df


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

    # ---- LAYER 2: confidence-bound trigger vs vanilla ----
    # This is the actual comparison that justifies scaling to yhat_upper instead of
    # yhat: how many MORE concurrent executions would you provision under the
    # enhanced approach vs vanilla, for the exact same forecast?
    scaled = compute_required_concurrency(future_only)
    print("\n--- Layer 2: required concurrency, vanilla vs enhanced trigger ---")
    print(scaled[["ds", "yhat", "yhat_upper", "required_concurrency_vanilla", "required_concurrency_enhanced"]].head(10))
    avg_vanilla = scaled["required_concurrency_vanilla"].mean()
    avg_enhanced = scaled["required_concurrency_enhanced"].mean()
    print(f"\nAvg required concurrency -- vanilla (yhat): {avg_vanilla:.1f}")
    print(f"Avg required concurrency -- enhanced (yhat_upper + 10% buffer): {avg_enhanced:.1f}")
    print(f"Enhanced provisions {(avg_enhanced / avg_vanilla - 1) * 100:.0f}% more capacity on average")
    print("(For spiky traffic this gap should be large -- that's the headroom that")
    print(" prevents cold starts when the real spike hits. For steady traffic the gap")
    print(" should be small, since yhat and yhat_upper are already close together.)")

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