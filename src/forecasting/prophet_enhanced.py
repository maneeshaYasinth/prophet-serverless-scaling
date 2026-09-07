"""
Enhanced Prophet (condition 3 of the 3x3 design).

Each of the four layers is a separate function so you can log which layers are
active per run (docs/EXPERIMENT_LOG.md) and do layer-activation analysis later
without needing a full ablation study.
"""

import pandas as pd
import numpy as np
from prophet import Prophet


def build_enhanced_model(interval_width: float = 0.95) -> Prophet:
    return Prophet(interval_width=interval_width)


# --- Layer 1: custom CloudWatch regressors ---------------------------------

def add_cloudwatch_regressors(model: Prophet, regressor_columns: list[str]) -> Prophet:
    """
    regressor_columns: names of exogenous CloudWatch signal columns already present
    in the training dataframe (e.g. concurrent_executions, throttle_count, duration_ms).
    Call this BEFORE model.fit().
    """
    for col in regressor_columns:
        model.add_regressor(col)
    return model


# --- Layer 2: confidence-bound scaling trigger ------------------------------

def compute_required_concurrency(forecast_df: pd.DataFrame, buffer_percent: float = 10.0) -> pd.DataFrame:
    """
    Scales to yhat_upper (not yhat) to avoid under-provisioning, plus AWS's
    recommended buffer on top.
    """
    forecast_df = forecast_df.copy()
    forecast_df["required_concurrency"] = (
        forecast_df["yhat_upper"].clip(lower=0) * (1 + buffer_percent / 100)
    ).round().astype(int)
    return forecast_df


# --- Layer 3: z-score residual anomaly detection ----------------------------

def detect_anomalies(actual: pd.Series, predicted: pd.Series, threshold: float = 2.0) -> pd.Series:
    """
    Returns a boolean series flagging points where the residual exceeds +/- threshold
    standard deviations -- these should trigger an emergency scaling override that
    bypasses waiting for the next scheduled forecast cycle.
    """
    residuals = actual - predicted
    z_scores = (residuals - residuals.mean()) / residuals.std()
    return z_scores.abs() > threshold


# --- Layer 4: adaptive retraining -------------------------------------------

def get_retrain_window(full_history: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    """
    Returns only the most recent `window_hours` of data for refitting, so the
    model doesn't drift on stale patterns.
    """
    cutoff = full_history["ds"].max() - pd.Timedelta(hours=window_hours)
    return full_history[full_history["ds"] > cutoff]


if __name__ == "__main__":
    # Wire the four layers together -- fill in once real CloudWatch data is available
    pass
