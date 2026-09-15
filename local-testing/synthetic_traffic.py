import numpy as np
import pandas as pd


def generate_steady(hours: int = 48, freq_minutes: int = 5, base_rps: float = 20, noise_pct: float = 5) -> pd.DataFrame:
    periods = int(hours * 60 / freq_minutes)
    ds = pd.date_range("2026-01-01", periods=periods, freq=f"{freq_minutes}min")
    noise = np.random.normal(0, base_rps * noise_pct / 100, periods)
    y = base_rps + noise
    return pd.DataFrame({"ds": ds, "y": y.clip(min=0)})


def generate_spiky(hours: int = 48, freq_minutes: int = 5, base_rps: float = 10,
                    spike_multiplier: float = 8, spike_duration_minutes: int = 15,
                    spike_every_minutes: int = 120) -> pd.DataFrame:
    periods = int(hours * 60 / freq_minutes)
    ds = pd.date_range("2026-01-01", periods=periods, freq=f"{freq_minutes}min")
    y = np.full(periods, base_rps, dtype=float)

    spike_len_steps = max(1, spike_duration_minutes // freq_minutes)
    spike_every_steps = max(1, spike_every_minutes // freq_minutes)
    for start in range(0, periods, spike_every_steps):
        end = min(start + spike_len_steps, periods)
        y[start:end] = base_rps * spike_multiplier

    noise = np.random.normal(0, base_rps * 0.05, periods)
    return pd.DataFrame({"ds": ds, "y": (y + noise).clip(min=0)})


def generate_seasonal(hours: int = 48, freq_minutes: int = 5, base_rps: float = 15,
                       daily_amplitude_pct: float = 60) -> pd.DataFrame:
    periods = int(hours * 60 / freq_minutes)
    ds = pd.date_range("2026-01-01", periods=periods, freq=f"{freq_minutes}min")
    t = np.arange(periods)
    period_steps = 24 * 60 / freq_minutes  # one day, in steps
    seasonal = 1 + (daily_amplitude_pct / 100) * np.sin(2 * np.pi * t / period_steps)
    noise = np.random.normal(0, base_rps * 0.05, periods)
    y = base_rps * seasonal + noise
    return pd.DataFrame({"ds": ds, "y": y.clip(min=0)})


if __name__ == "__main__":
    for name, df in [
        ("steady", generate_steady()),
        ("spiky", generate_spiky()),
        ("seasonal", generate_seasonal()),
    ]:
        df.to_csv(f"data/processed/{name}_traffic.csv", index=False)
        print(f"{name}: {len(df)} rows -> data/processed/{name}_traffic.csv")
