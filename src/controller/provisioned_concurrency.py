"""
Separate process from snip-infra: reads Prophet's forecast output and calls the
AWS Provisioned Concurrency API ahead of predicted demand.

IMPORTANT: put_provisioned_concurrency_config does not allocate instantly.
The call returns Status="IN_PROGRESS" and takes real time to reach "READY".
Your forecast lead_time (see configs/experiment_config.yaml) must be longer
than this allocation delay, or you'll be pre-warming too late. Log actual
observed allocation time per run so you can validate this assumption with data.
"""

import time
import boto3


def set_provisioned_concurrency(
    function_name: str,
    qualifier: str,
    required_concurrency: int,
    region: str = "ap-south-1",
) -> dict:
    client = boto3.client("lambda", region_name=region)
    response = client.put_provisioned_concurrency_config(
        FunctionName=function_name,
        Qualifier=qualifier,
        ProvisionedConcurrentExecutions=required_concurrency,
    )
    return response


def wait_until_ready(function_name: str, qualifier: str, region: str = "ap-south-1", poll_seconds: int = 5) -> float:
    """
    Polls until the PC allocation reaches READY, returns elapsed seconds.
    Use this during experiments to measure actual allocation lag -- this is
    the number that validates (or invalidates) your chosen forecast lead time.
    """
    client = boto3.client("lambda", region_name=region)
    start = time.time()
    while True:
        resp = client.get_provisioned_concurrency_config(FunctionName=function_name, Qualifier=qualifier)
        if resp["Status"] == "READY":
            return time.time() - start
        time.sleep(poll_seconds)


if __name__ == "__main__":
    # Example -- wire this up to consume prophet_enhanced.compute_required_concurrency() output
    pass
