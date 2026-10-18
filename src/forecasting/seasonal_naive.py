"""
Seasonal-naive baseline forecaster: "the next value equals the value one cycle ago".

    yhat(t + h) = y(t + h - P)        P = seasonal period

It learns nothing, which is the point: it is the standard benchmark for seasonal
series (Hyndman & Athanasopoulos, Forecasting: Principles and Practice). If
Prophet cannot beat it, Prophet's accuracy is not what justifies using it.

The band comes from the window's own seasonal differences y(s) - y(s - P): their
(1 - w)/2 and (1 + w)/2 quantiles, added to yhat. That gives an empirical
interval comparable with Prophet's yhat_lower / yhat_upper, so coverage and
Layer 2 can be compared on equal terms. Horizons up to one period only: past
that, the value one cycle back would itself be a forecast.
"""

import pandas as pd


def seasonal_naive_forecast(train: pd.DataFrame, future_ds: pd.Series, period_minutes: int,
                            interval_width: float) -> pd.DataFrame:
    """train: ds, y at 1-minute steps. Returns ds, yhat, yhat_lower, yhat_upper for future_ds."""
    period = pd.Timedelta(minutes=period_minutes)
    if (future_ds.max() - train.ds.max()) > period:
        raise ValueError("seasonal naive needs horizon <= one period")
    y = train.set_index("ds")["y"]

    diffs = (y - y.shift(freq=period)).dropna()  # y(s) - y(s - P) inside the window
    if diffs.empty:
        raise ValueError("training window shorter than one period plus one minute")
    lo = diffs.quantile((1 - interval_width) / 2)
    hi = diffs.quantile((1 + interval_width) / 2)

    yhat = y.reindex(future_ds - period).to_numpy()
    return pd.DataFrame({"ds": future_ds.to_numpy(), "yhat": yhat, "yhat_lower": yhat + lo, "yhat_upper": yhat + hi})
