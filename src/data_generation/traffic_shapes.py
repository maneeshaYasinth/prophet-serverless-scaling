"""Load shapes for the three traffic patterns in the 3x3 design.

Choose a pattern with an env var:
    TRAFFIC_PATTERN=steady | spiky | seasonal

Import this class into your existing boto3-invoke locustfile so Locust
picks it up:
    from traffic_shapes import TrafficPatternShape
"""
import math
import os
import random

from locust import LoadTestShape


class TrafficPatternShape(LoadTestShape):
    pattern = os.getenv("TRAFFIC_PATTERN", "steady")
    duration_s = int(os.getenv("DURATION_S", "3600"))
    base_users = int(os.getenv("BASE_USERS", "20"))
    seed = int(os.getenv("SEED", "42"))  # same seed -> same spike schedule

    # Seasonal: a compressed cycle (default 30 min) so Prophet sees
    # several full cycles in one run instead of needing days of traffic.
    season_period_s = int(os.getenv("SEASON_PERIOD_S", "1800"))
    season_amplitude = 0.6  # load swings +/-60% around the base

    # Spiky: short bursts at a multiple of the base load.
    spike_multiplier = 5
    spikes_per_hour = int(os.getenv("SPIKES_PER_HOUR", "6"))

    def __init__(self):
        super().__init__()
        rng = random.Random(self.seed)
        n_spikes = round(self.spikes_per_hour * self.duration_s / 3600)
        self.spikes = []
        for _ in range(n_spikes):
            start = rng.uniform(0, self.duration_s - 120)
            self.spikes.append((start, start + rng.uniform(60, 120)))

    def tick(self):
        t = self.get_run_time()
        if t >= self.duration_s:
            return None  # stop the test

        if self.pattern == "steady":
            users = self.base_users
        elif self.pattern == "seasonal":
            phase = 2 * math.pi * t / self.season_period_s
            users = self.base_users * (1 + self.season_amplitude * math.sin(phase))
        elif self.pattern == "spiky":
            in_spike = any(start <= t < end for start, end in self.spikes)
            users = self.base_users * (self.spike_multiplier if in_spike else 1)
        else:
            raise ValueError(f"Unknown TRAFFIC_PATTERN: {self.pattern}")

        users = max(1, round(users))
        # spawn_rate = users means the target is reached in about 1s,
        # which keeps spikes sharp instead of ramping slowly.
        return users, users
