"""
Collects the three headline metrics for a single scenario run and writes them
in a consistent format so all 9 scenarios (3 conditions x 3 traffic patterns)
can be compared directly.
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class ScenarioResult:
    condition: str          # reactive-baseline | vanilla-prophet | enhanced-prophet
    traffic_pattern: str    # steady | spiky | seasonal
    p95_latency_ms: float
    p99_latency_ms: float
    cold_start_count: int
    cost_per_request_usd: float
    active_layers: list[str] | None = None  # for enhanced-prophet runs only


def save_result(result: ScenarioResult, results_dir: str = "results") -> str:
    Path(results_dir).mkdir(exist_ok=True)
    filename = f"{results_dir}/{result.condition}_{result.traffic_pattern}.json"
    with open(filename, "w") as f:
        json.dump(asdict(result), f, indent=2)
    return filename


def load_all_results(results_dir: str = "results") -> list[dict]:
    results = []
    for path in Path(results_dir).glob("*.json"):
        with open(path) as f:
            results.append(json.load(f))
    return results
