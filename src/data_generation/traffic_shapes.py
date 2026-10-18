"""Load shapes for the three traffic patterns in the 3x3 design.

Choose a pattern with an env var:
    TRAFFIC_PATTERN=steady | spiky | seasonal

Loaded by locust_scenarios/sandbox_locustfile_patterns.py. Optional realism
(NOISE_PCT, NOISE_INTERVAL_S, DRIFT_PCT) is off by default; see the class.
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

    # Realism (all patterns). Defaults 0 = the original noiseless shapes, so earlier
    # runs reproduce; experiment values live in experiment_config.yaml and are
    # passed in by loadgen/run_experiment.sh.
    # Noise: each NOISE_INTERVAL_S the user count is scaled by (1 + e), e ~ N(0, NOISE_PCT%)
    # capped at +/-3 sigma, so traffic wobbles around its pattern instead of
    # repeating exactly (a copy-last-cycle forecast would otherwise be near-perfect).
    noise_pct = float(os.getenv("NOISE_PCT", "0"))
    noise_interval_s = int(os.getenv("NOISE_INTERVAL_S", "60"))
    # Drift: the base level changes linearly by DRIFT_PCT% over the whole run,
    # like a service gaining users; tests trend handling and retraining.
    drift_pct = float(os.getenv("DRIFT_PCT", "0"))

    def __init__(self):
        super().__init__()
        rng = random.Random(self.seed)
        n_spikes = round(self.spikes_per_hour * self.duration_s / 3600)
        self.spikes = []
        for _ in range(n_spikes):
            start = rng.uniform(0, self.duration_s - 120)
            self.spikes.append((start, start + rng.uniform(60, 120)))

        # Own RNG stream, so noise settings never change the spike schedule above
        noise_rng = random.Random(f"{self.seed}-noise")
        sigma = self.noise_pct / 100
        self.noise = [max(-3 * sigma, min(3 * sigma, noise_rng.gauss(0, sigma)))
                      for _ in range(self.duration_s // self.noise_interval_s + 1)]

    def users_at(self, t: float) -> int:
        """Target user count at run time t (seconds). Pure: same t, same answer."""
        base = self.base_users * (1 + self.drift_pct / 100 * t / self.duration_s)
        if self.pattern == "steady":
            users = base
        elif self.pattern == "seasonal":
            phase = 2 * math.pi * t / self.season_period_s
            users = base * (1 + self.season_amplitude * math.sin(phase))
        elif self.pattern == "spiky":
            in_spike = any(start <= t < end for start, end in self.spikes)
            users = base * (self.spike_multiplier if in_spike else 1)
        else:
            raise ValueError(f"Unknown TRAFFIC_PATTERN: {self.pattern}")
        users *= 1 + self.noise[int(t // self.noise_interval_s)]
        return max(1, round(users))

    def tick(self):
        t = self.get_run_time()
        if t >= self.duration_s:
            return None  # stop the test

        users = self.users_at(t)
        # spawn_rate = users means the target is reached in about 1s,
        # which keeps spikes sharp instead of ramping slowly.
        return users, users
