"""
Sandbox Lambda handler for pipeline validation.

Simulates a slow cold-start init (e.g. loading a large dependency, warming a
connection pool) via SIMULATED_INIT_DELAY_SECONDS, so Provisioned Concurrency
pre-warming has something real and observable to protect against. The delay
runs once at import time (module load = the actual Lambda cold-start path),
not inside the handler, so a warm/pre-warmed invocation is fast and a genuine
cold start is slow.
"""

import json
import os
import time

_INIT_DELAY_SECONDS = float(os.environ.get("SIMULATED_INIT_DELAY_SECONDS", "0"))

if _INIT_DELAY_SECONDS > 0:
    time.sleep(_INIT_DELAY_SECONDS)

# Set once per execution environment (i.e. per real cold start). Reused
# across invocations on the same warm container.
_is_first_invocation = True


def handler(event, context):
    global _is_first_invocation
    was_cold_start = _is_first_invocation
    _is_first_invocation = False

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "message": "sandbox-lambda ok",
                "cold_start": was_cold_start,
                "simulated_init_delay_seconds": _INIT_DELAY_SECONDS,
                "request_id": getattr(context, "aws_request_id", None),
            }
        ),
    }
