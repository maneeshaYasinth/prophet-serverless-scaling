"""
Layer 3: Z-Score Residual Anomaly Detection
=============================================

Compares actual observed traffic against Prophet's point forecast (yhat).
If the residual (actual - yhat) deviates more than `z_threshold` standard
deviations from the recent residual distribution, this fires an
"emergency" signal that bypasses the normal forecast-driven scaling
decision for that interval.

Why this exists: Prophet forecasts on a cycle (e.g. every 5-10 minutes).
A burst that starts mid-cycle won't be reflected in the forecast until the
next refit/predict call. This layer is a fast, cheap statistical check
that runs on every new actual data point and can react between forecast
cycles.

This module holds no AWS or Prophet dependency -- it only needs a stream
of (actual, yhat) pairs, so it's independently testable.
"""

import math
import statistics
from collections import deque


class ZScoreAnomalyDetector:
    def __init__(self, window_size=30, z_threshold=2.0):
        """
        Args:
            window_size: number of recent residuals kept for computing the
                rolling mean/std. 30 points is a reasonable starting point
                for ~1-minute-granularity CloudWatch data (30 minutes of
                history) -- tune this once real data is collected.
            z_threshold: number of standard deviations beyond which a
                residual counts as an anomaly. +-2 sigma matches the
                enhancement-layer design in the dissertation.
        """
        self.window_size = window_size
        self.z_threshold = z_threshold
        self._residuals = deque(maxlen=window_size)

    def update_and_check(self, actual, yhat):
        """
        Feed in one new (actual, yhat) pair.

        Returns:
            dict with the residual, z-score, and whether this point counts
            as an anomaly -- suitable for logging straight into
            docs/EXPERIMENT_LOG.md or a results CSV.
        """
        residual = actual - yhat

        is_anomaly = False
        z_score = 0.0

        # Need at least 2 prior points to compute a meaningful stdev.
        if len(self._residuals) >= 2:
            mean = statistics.mean(self._residuals)
            stdev = statistics.pstdev(self._residuals)
            if stdev > 0:
                z_score = (residual - mean) / stdev
                is_anomaly = abs(z_score) > self.z_threshold

        self._residuals.append(residual)

        return {
            "actual": actual,
            "yhat": yhat,
            "residual": residual,
            "z_score": z_score,
            "is_anomaly": is_anomaly,
        }

    def emergency_target_concurrency(
        self,
        actual,
        requests_per_instance=10,
        safety_margin=1.3,
        min_concurrency=1,
    ):
        """
        When an anomaly fires, bypass the forecast entirely and provision
        based on the actual observed value plus a safety margin, since the
        forecast can no longer be trusted to be tracking reality in this
        moment.

        safety_margin=1.3 means "provision 30% above what we just saw" --
        a placeholder worth tuning once you have real burst data.
        """
        target = math.ceil((actual * safety_margin) / requests_per_instance)
        return max(target, min_concurrency)
