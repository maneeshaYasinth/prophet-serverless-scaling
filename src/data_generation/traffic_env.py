"""
Print the config's traffic_realism settings as shell exports for TrafficPatternShape.

Used by loadgen/run_experiment.sh:  eval "$(venv/bin/python -m src.data_generation.traffic_env)"
so the values come from experiment_config.yaml, not from the script.
"""

import yaml

from src.evaluation.rolling_forecast import CONFIG_PATH

ENV_NAMES = {"noise_pct": "NOISE_PCT", "noise_interval_s": "NOISE_INTERVAL_S", "drift_pct": "DRIFT_PCT"}

if __name__ == "__main__":
    realism = yaml.safe_load(CONFIG_PATH.read_text()).get("traffic_realism", {})
    for key, env in ENV_NAMES.items():
        print(f"export {env}={realism.get(key, 0)}")
