"""
Condition 1: reactive baseline -- AWS Lambda's default scaling behavior with
no forecasting layer and no Provisioned Concurrency configured at all.

For now this targets sandbox-lambda (via the boto3-invoke Locust user in
src/data_generation/locust_scenarios/sandbox_user.py) rather than snip-infra,
to validate the whole measurement pipeline -- Locust -> boto3 invoke ->
per-request log -> ScenarioResult -- on a safe throwaway target first. Point
LOCUSTFILE_BY_PATTERN at traffic_shapes.py (the HTTP/snip-infra user) once
you're ready to move past sandbox validation.

Usage:
    python -m src.baseline.reactive_autoscaling steady
    python -m src.baseline.reactive_autoscaling spiky
    python -m src.baseline.reactive_autoscaling seasonal
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

from src.evaluation.metrics import ScenarioResult, save_result

LOCUST_SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "data_generation" / "locust_scenarios"

LOCUSTFILE_BY_PATTERN = {
    "steady": LOCUST_SCENARIOS_DIR / "sandbox_locustfile_steady.py",
    "spiky": LOCUST_SCENARIOS_DIR / "sandbox_locustfile_spiky.py",
    "seasonal": LOCUST_SCENARIOS_DIR / "sandbox_locustfile_seasonal.py",
}

# ap-south-1 on-demand pricing, x86_64, 128 MB -- see https://aws.amazon.com/lambda/pricing/
# and re-check if this drifts; kept as constants here rather than an API call
# since pricing barely moves and a live lookup isn't worth the extra dependency.
PRICE_PER_GB_SECOND_USD = 0.0000166667
PRICE_PER_REQUEST_USD = 0.0000002
LAMBDA_MEMORY_GB = 128 / 1024


def run_locust(pattern: str, log_path: Path) -> None:
    locustfile = LOCUSTFILE_BY_PATTERN[pattern]
    if log_path.exists():
        log_path.unlink()

    env = {**os.environ, "SANDBOX_INVOKE_LOG": str(log_path.resolve())}
    result = subprocess.run(
        ["locust", "-f", str(locustfile), "--headless"],
        cwd=LOCUST_SCENARIOS_DIR,
        env=env,
    )
    if result.returncode != 0:
        print(f"locust exited with code {result.returncode}", file=sys.stderr)


def _percentile(sorted_data: list[float], pct: float) -> float:
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (pct / 100)
    f_idx, c_idx = int(k), min(int(k) + 1, len(sorted_data) - 1)
    if f_idx == c_idx:
        return sorted_data[f_idx]
    return sorted_data[f_idx] + (sorted_data[c_idx] - sorted_data[f_idx]) * (k - f_idx)


def summarize(log_path: Path, condition: str, pattern: str) -> ScenarioResult:
    response_times: list[float] = []
    billed_durations_ms: list[float] = []
    cold_starts = 0

    with open(log_path) as f:
        for line in f:
            record = json.loads(line)
            if record["error"]:
                continue
            response_times.append(record["response_time_ms"])
            if record.get("cold_start"):
                cold_starts += 1
            if record.get("billed_duration_ms"):
                billed_durations_ms.append(record["billed_duration_ms"])

    response_times.sort()
    avg_billed_s = (statistics.mean(billed_durations_ms) / 1000) if billed_durations_ms else 0.0
    cost_per_request = (avg_billed_s * LAMBDA_MEMORY_GB * PRICE_PER_GB_SECOND_USD) + PRICE_PER_REQUEST_USD

    return ScenarioResult(
        condition=condition,
        traffic_pattern=pattern,
        p95_latency_ms=round(_percentile(response_times, 95), 2),
        p99_latency_ms=round(_percentile(response_times, 99), 2),
        cold_start_count=cold_starts,
        cost_per_request_usd=round(cost_per_request, 8),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run the reactive baseline (condition 1) for one traffic pattern."
    )
    parser.add_argument("pattern", choices=["steady", "spiky", "seasonal"])
    parser.add_argument(
        "--log-path",
        default=None,
        help="Where to write the per-request JSONL log (default: results/reactive_baseline_<pattern>_log.jsonl)",
    )
    args = parser.parse_args()

    log_path = Path(args.log_path or f"results/reactive_baseline_{args.pattern}_log.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Running reactive baseline / {args.pattern} against sandbox-lambda...")
    run_locust(args.pattern, log_path)

    result = summarize(log_path, condition="reactive-baseline", pattern=args.pattern)
    output_path = save_result(result)
    print(f"Saved: {output_path}")
    print(result)


if __name__ == "__main__":
    main()
