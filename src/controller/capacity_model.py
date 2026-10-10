"""
Forecast -> Provisioned Concurrency conversion, calibrated from measured data.

Little's law (concurrency = request rate x duration) predicts about 1
concurrent environment for sandbox-lambda (200 req/s x ~5 ms), but CloudWatch
measured 7-28. The per-minute ConcurrentExecutions peak is driven by Lambda's
per-invoke overhead and by burstiness within the minute, neither of which the
billed duration captures. So instead of an assumed formula, the conversion is
a linear fit of measured concurrency against request rate from a warm-up run:

    target = ceil((intercept + slope * rate + headroom) * (1 + buffer_percent / 100))

- intercept, slope: least-squares fit of CloudWatch ConcurrentExecutions
  (per-minute max) on Invocations / 60 (req/s).
- headroom: a residual quantile (e.g. 95th), so the fit covers that share of
  observed minutes rather than the average one. Under-provisioning causes cold
  starts, over-provisioning only costs money, so the fit is deliberately
  conservative.
- buffer_percent: AWS's recommended margin on top (aws.pc_buffer_percent).

The forecast-uncertainty margin is NOT in here: that is Layer 2's job (feed
yhat_upper instead of yhat). Keeping the two separate means C2 and C3 use the
identical conversion and differ only in which forecast field they feed in.
"""

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class CapacityModel:
    intercept: float
    slope_per_rps: float
    headroom: float
    buffer_percent: float = 0.0
    interval_seconds: int = 60  # forecasts are invocations per interval
    min_concurrency: int = 1
    max_concurrency: int | None = None

    @classmethod
    def fit(cls, df: pd.DataFrame, quantile: float, buffer_percent: float, interval_seconds: int = 60):
        """df needs y (invocations per interval) and concurrency (peak per interval)."""
        rate = df["y"] / interval_seconds
        slope, intercept = np.polyfit(rate, df["concurrency"], 1)
        residuals = df["concurrency"] - (intercept + slope * rate)
        return cls(
            intercept=float(intercept),
            slope_per_rps=float(slope),
            headroom=float(residuals.quantile(quantile)),
            buffer_percent=buffer_percent,
            interval_seconds=interval_seconds,
        )

    def target(self, forecast_per_interval: float) -> int:
        rate = max(forecast_per_interval, 0) / self.interval_seconds  # never provision for negative demand
        raw = (self.intercept + self.slope_per_rps * rate + self.headroom) * (1 + self.buffer_percent / 100)
        target = max(math.ceil(raw), self.min_concurrency)
        if self.max_concurrency is not None:
            target = min(target, self.max_concurrency)
        return target

    def save(self, path: Path, **metadata) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**asdict(self), **metadata}, indent=2))

    @classmethod
    def load(cls, path: Path, **overrides):
        data = json.loads(Path(path).read_text())
        fields = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**{**fields, **overrides})
