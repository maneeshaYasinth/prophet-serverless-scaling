"""
Locust User that invokes sandbox-lambda directly via boto3's Invoke API,
instead of over HTTP through a Function URL. This sidesteps the new-account
restriction on anonymous Function URL access (see docs/EXPERIMENT_LOG.md) --
a boto3 invoke is a normal signed call under your own credentials -- and it's
also a closer match to how the eventual controller will call the function
than an HTTP round-trip would be.

Uses LogType="Tail" on every invoke to pull the REPORT line's billed
duration straight out of CloudWatch's returned log tail, so per-request cost
can be computed without a separate CloudWatch Logs query.

Each invocation is appended as one JSON line to SANDBOX_INVOKE_LOG, which
reactive_autoscaling.py reads afterward to compute p95/p99 latency, cold
start count, and cost per request.
"""

import base64
import json
import os
import re
import threading
import time

import boto3
from locust import User, events, task

REGION = os.environ.get("SANDBOX_REGION", "ap-south-1")
FUNCTION_NAME = os.environ.get("SANDBOX_FUNCTION_NAME", "sandbox-lambda")
QUALIFIER = os.environ.get("SANDBOX_QUALIFIER", "prod")
LOG_PATH = os.environ.get("SANDBOX_INVOKE_LOG", "sandbox_invoke_log.jsonl")

_BILLED_DURATION_RE = re.compile(r"Billed Duration:\s*([\d.]+)\s*ms")
_log_lock = threading.Lock()


def _log_invocation(record: dict) -> None:
    with _log_lock:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")


class LambdaInvokeUser(User):
    """Reports each boto3 invoke to Locust's stats via events.request.fire(),
    the same way HttpUser reports HTTP calls, so Locust's live dashboard and
    --headless summary work normally even though nothing here is HTTP."""

    abstract = False

    def on_start(self):
        self._client = boto3.client("lambda", region_name=REGION)

    @task
    def invoke(self):
        start = time.perf_counter()
        exception = None
        cold_start = None
        billed_duration_ms = None
        response_length = 0

        try:
            response = self._client.invoke(
                FunctionName=FUNCTION_NAME,
                Qualifier=QUALIFIER,
                InvocationType="RequestResponse",
                LogType="Tail",
                Payload=b"{}",
            )
            raw_payload = response["Payload"].read()
            response_length = len(raw_payload)

            if response.get("FunctionError"):
                exception = Exception(f"Lambda FunctionError: {raw_payload[:200]!r}")
            else:
                body = json.loads(json.loads(raw_payload)["body"])
                cold_start = body.get("cold_start")

            log_result = response.get("LogResult")
            if log_result:
                decoded = base64.b64decode(log_result).decode("utf-8", errors="replace")
                match = _BILLED_DURATION_RE.search(decoded)
                if match:
                    billed_duration_ms = float(match.group(1))
        except Exception as e:  # noqa: BLE001 -- Locust needs the raw exception for its stats
            exception = e

        response_time_ms = (time.perf_counter() - start) * 1000

        events.request.fire(
            request_type="LambdaInvoke",
            name=FUNCTION_NAME,
            response_time=response_time_ms,
            response_length=response_length,
            exception=exception,
            context={},
        )

        _log_invocation(
            {
                "timestamp": time.time(),
                "response_time_ms": response_time_ms,
                "cold_start": cold_start,
                "billed_duration_ms": billed_duration_ms,
                "error": str(exception) if exception else None,
            }
        )
