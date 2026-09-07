"""
Locust load shapes for the three traffic patterns, driven by configs/experiment_config.yaml.
Run these against snip-infra to generate the real CloudWatch data that replaces the
synthetic data currently used in prophet_baseline.py.

Usage: locust -f traffic_shapes.py --headless
"""

from locust import HttpUser, task, LoadTestShape
import math


class SnipInfraUser(HttpUser):
    @task
    def shorten_and_redirect(self):
        # TODO: point at your actual snip-infra endpoints
        self.client.post("/shorten", json={"url": "https://example.com"})


class SteadyShape(LoadTestShape):
    """Roughly constant load with small noise -- baseline pattern."""
    base_users = 20
    run_time = 600

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
    spike_every = 600     # seconds
    run_time = 1800

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
    run_time = 3600

    def tick(self):
        run_time = self.get_run_time()
        if run_time > self.run_time:
            return None
        multiplier = 1 + (self.amplitude_pct / 100) * math.sin(2 * math.pi * run_time / self.period_seconds)
        users = max(1, int(self.base_users * multiplier))
        return (users, 5)
