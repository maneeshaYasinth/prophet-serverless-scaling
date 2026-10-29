"""
Forecast -> Provisioned Concurrency conversion, calibrated from measured data.

Little's law (concurrency = request rate x duration) predicts about 1
concurrent environment for sandbox-lambda (200 req/s x ~5 ms), but CloudWatch
measured 7-28. The per-minute ConcurrentExecutions peak is driven by Lambda's
per-invoke overhead and by burstiness within the minute, neither of which the
billed duration captures. So instead of an assumed formula, the conversion is
a linear fit of measured concurrency against request rate from a warm-up run:

    additive:        target = ceil((intercept + slope * rate + headroom) * (1 + buffer_percent / 100))
    multiplicative:  target = ceil((intercept + slope * rate) * headroom_factor * (1 + buffer_percent / 100))

- intercept, slope: least-squares fit of CloudWatch ConcurrentExecutions
  (per-minute max) on Invocations / 60 (req/s).
- headroom (additive): a residual quantile (e.g. 95th), so the fit covers that
  share of observed minutes rather than the average one. Under-provisioning
  causes cold starts, over-provisioning only costs money, so the fit is
  deliberately conservative.
- headroom_factor (multiplicative): the same quantile of actual / fitted. The
  scatter around the line grows with load (Run 2026-10-29-1: residual standard
  deviation 0.67 below 150 req/s, 3.09 above 320), so a margin proportional to
  the fit is tighter at low load and wider at high load than a constant one.
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
    headroom: float = 0.0
    buffer_percent: float = 0.0
    interval_seconds: int = 60  # forecasts are invocations per interval
    min_concurrency: int = 1
    max_concurrency: int | None = None
    headroom_mode: str = "additive"  # older calibration files have no field: additive
    headroom_factor: float = 1.0

    @classmethod
    def fit(cls, df: pd.DataFrame, quantile: float, buffer_percent: float, interval_seconds: int = 60,
            headroom_mode: str = "additive"):
        """df needs y (invocations per interval) and concurrency (peak per interval)."""
        rate = df["y"] / interval_seconds
        slope, intercept = np.polyfit(rate, df["concurrency"], 1)
        fitted = intercept + slope * rate
        if headroom_mode == "additive":
            margin = {"headroom": float((df["concurrency"] - fitted).quantile(quantile))}
        elif headroom_mode == "multiplicative":
            margin = {"headroom_factor": float((df["concurrency"] / fitted).quantile(quantile))}
        else:
            raise ValueError(f"unknown headroom_mode {headroom_mode!r}")
        return cls(
            intercept=float(intercept),
            slope_per_rps=float(slope),
            buffer_percent=buffer_percent,
            interval_seconds=interval_seconds,
            headroom_mode=headroom_mode,
            **margin,
        )

    def provisioned(self, rate):
        """Fit plus margin at a request rate (req/s), before the buffer and rounding up."""
        fitted = self.intercept + self.slope_per_rps * rate
        if self.headroom_mode == "multiplicative":
            return fitted * self.headroom_factor
        return fitted + self.headroom

    def margin_label(self) -> str:
        if self.headroom_mode == "multiplicative":
            return f"Fit x {self.headroom_factor:.2f}"
        return f"Fit + headroom ({self.headroom:.1f})"

    def target(self, forecast_per_interval: float) -> int:
        rate = max(forecast_per_interval, 0) / self.interval_seconds  # never provision for negative demand
        raw = self.provisioned(rate) * (1 + self.buffer_percent / 100)
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
