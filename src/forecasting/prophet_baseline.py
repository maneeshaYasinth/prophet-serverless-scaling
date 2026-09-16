"""
Vanilla Prophet baseline (condition 2 of the 3x3 experimental design).

This is a rebuilt starting point matching the earlier `prophet_starter.py` work:
fits plain Prophet (no custom layers) across steady/spiky/seasonal traffic, so it
can serve as the baseline that the enhanced framework (prophet_enhanced.py) is
compared against.

NOTE: this was reconstructed from the project's notes, not copied from the original
file. Compare this against your actual prophet_starter.py before treating it as
your source of truth -- reconcile any differences.
"""

import pandas as pd
from prophet import Prophet


def load_traffic_data(csv_path: str) -> pd.DataFrame:
    """
    Expects a CSV with at least columns: ds (timestamp), y (request count or concurrency).
    Swap this for a real CloudWatch/Locust export loader once available --
    see src/data_generation/ for the Locust scenario scripts that produce these logs.
    """
    df = pd.read_csv(csv_path, parse_dates=["ds"])
    return df[["ds", "y"]]


def fit_vanilla_prophet(df: pd.DataFrame, interval_width: float = 0.95) -> Prophet:
    """Fits a plain Prophet model with no regressors or custom layers."""
    model = Prophet(interval_width=interval_width)
    model.fit(df)
    return model


def forecast(model: Prophet, periods: int, freq: str = "min") -> pd.DataFrame:
    """
    Returns a dataframe with ds, yhat, yhat_lower, yhat_upper for the next `periods`
    time steps. yhat_upper is what the confidence-bound trigger layer will consume
    in the enhanced version -- vanilla Prophet doesn't use it for scaling decisions,
    which is part of what this baseline is meant to illustrate.
    """
    future = model.make_future_dataframe(periods=periods, freq=freq)
    fcst = model.predict(future)
    return fcst[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(periods)


if __name__ == "__main__":
    # Example run against one traffic pattern -- repeat for steady / spiky / seasonal
    # and log each run in docs/EXPERIMENT_LOG.md
    df = load_traffic_data("testing/pattern_exploration/data/processed/spiky_traffic.csv")
    model = fit_vanilla_prophet(df)
    result = forecast(model, periods=60)
    print(result)

    # Known finding to watch for: spiky traffic tends to produce wide, negative-floored
    # yhat_lower values with vanilla Prophet -- this is the concrete motivation for the
    # confidence-bound trigger layer in prophet_enhanced.py.
