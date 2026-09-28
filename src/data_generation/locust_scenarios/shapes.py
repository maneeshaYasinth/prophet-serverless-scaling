"""
Locust load shapes for the three traffic patterns, driven by
configs/experiment_config.yaml's intent (steady/spiky/seasonal). Shared
between traffic_shapes.py (HTTP, for snip-infra) and the boto3-invoke user
(for sandbox-lambda), since the shape logic doesn't depend on how a request
is actually sent.

Set SHAPE_RUN_TIME (seconds) to shorten a run for smoke testing, e.g.
SHAPE_RUN_TIME=60 python -m src.baseline.reactive_autoscaling steady
"""

import math
import os

from locust import LoadTestShape


class SteadyShape(LoadTestShape):
    """Roughly constant load with small noise -- baseline pattern."""

    base_users = 20
    run_time = int(os.environ.get("SHAPE_RUN_TIME", 600))

    def tick(self):
        run_time = self.get_run_time()
        if run_time > self.run_time:
            return None
        return (self.base_users, 5)


class SpikyShape(LoadTestShape):
    """Low baseline with sudden short spikes -- the pattern that stresses cold starts."""

    base_users = 10
    spike_multiplier = 8
    spike_duration = 180  # seconds
    spike_every = 600  # seconds
    run_time = int(os.environ.get("SHAPE_RUN_TIME", 1800))

    def tick(self):
        run_time = self.get_run_time()
        if run_time > self.run_time:
            return None
        in_spike = (run_time % self.spike_every) < self.spike_duration
        users = self.base_users * self.spike_multiplier if in_spike else self.base_users
        return (users, 10)


class SeasonalShape(LoadTestShape):
    """Smooth sinusoidal daily-cycle pattern, compressed into the test duration."""

    base_users = 15
    amplitude_pct = 60
    period_seconds = 1800  # compressed "day"
    run_time = int(os.environ.get("SHAPE_RUN_TIME", 3600))

    def tick(self):
        run_time = self.get_run_time()
        if run_time > self.run_time:
            return None
        multiplier = 1 + (self.amplitude_pct / 100) * math.sin(
            2 * math.pi * run_time / self.period_seconds
        )
        users = max(1, int(self.base_users * multiplier))
        return (users, 5)
