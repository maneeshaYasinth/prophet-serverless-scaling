"""
Quick sanity check: invokes sandbox-lambda directly via boto3's Invoke API
(not the Function URL), so it's unaffected by the new-account restriction on
anonymous Function URL access -- this is a normal signed call using your own
credentials.

Run twice in a row: first call should show "cold_start": true and take a
bit over SIMULATED_INIT_DELAY_SECONDS; second call should be fast with
"cold_start": false, since it reuses the same warm execution environment.
"""

import json

import boto3

REGION = "ap-south-1"
FUNCTION_NAME = "sandbox-lambda"
QUALIFIER = "prod"


def invoke_once():
    client = boto3.client("lambda", region_name=REGION)
    response = client.invoke(
        FunctionName=FUNCTION_NAME,
        Qualifier=QUALIFIER,
        InvocationType="RequestResponse",
        Payload=json.dumps({}).encode("utf-8"),
    )
    payload = json.loads(response["Payload"].read())
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    invoke_once()