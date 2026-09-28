"""
Measures how long Provisioned Concurrency actually takes to reach READY on
sandbox-lambda, across a few scale-up / scale-down steps, and appends each
measurement to results/pc_allocation_lag.csv.

This is the number that validates (or breaks) forecasting.lead_time_minutes in
configs/experiment_config.yaml: if allocation can take longer than the lead
time, the controller pre-warms too late.

Always deletes the PC config on exit (even on error / Ctrl-C), since PC bills
continuously while allocated.

Usage (from repo root, venv active):
    python measure_pc_lag.py
    python measure_pc_lag.py --steps 2 5 2 --timeout 900
"""

import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

from src.controller.provisioned_concurrency import set_provisioned_concurrency

FUNCTION_NAME = "sandbox-lambda"
QUALIFIER = "prod"
REGION = "ap-south-1"
CSV_PATH = Path("results/pc_allocation_lag.csv")


def wait_for_ready(client, timeout_s: int, poll_s: int = 3) -> tuple[float, str]:
    """Returns (elapsed_seconds, final_status). Stops on READY, FAILED, or timeout."""
    start = time.time()
    while True:
        resp = client.get_provisioned_concurrency_config(
            FunctionName=FUNCTION_NAME, Qualifier=QUALIFIER
        )
        status = resp["Status"]
        if status in ("READY", "FAILED"):
            return time.time() - start, status
        if time.time() - start > timeout_s:
            return time.time() - start, "TIMEOUT"
        time.sleep(poll_s)


def append_row(row: dict) -> None:
    CSV_PATH.parent.mkdir(exist_ok=True)
    new_file = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp_utc", "from_concurrency", "to_concurrency", "seconds_to_ready", "status"]
        )
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, nargs="+", default=[2, 5, 2],
                        help="Target PC values applied in order (default: 2 5 2)")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait per step")
    args = parser.parse_args()

    client = boto3.client("lambda", region_name=REGION)
    previous = 0

    try:
        for target in args.steps:
            print(f"Setting PC {previous} -> {target} ...")
            set_provisioned_concurrency(FUNCTION_NAME, QUALIFIER, target, region=REGION)
            elapsed, status = wait_for_ready(client, args.timeout)
            print(f"  {status} after {elapsed:.1f}s")
            append_row({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "from_concurrency": previous,
                "to_concurrency": target,
                "seconds_to_ready": round(elapsed, 1),
                "status": status,
            })
            if status != "READY":
                print("Stopping early: allocation did not reach READY.")
                break
            previous = target
    finally:
        print("Cleaning up: deleting PC config ...")
        try:
            client.delete_provisioned_concurrency_config(
                FunctionName=FUNCTION_NAME, Qualifier=QUALIFIER
            )
            print("  deleted.")
        except client.exceptions.ResourceNotFoundException:
            print("  nothing to delete.")


if __name__ == "__main__":
    main()
