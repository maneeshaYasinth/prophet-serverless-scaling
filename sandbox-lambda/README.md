# sandbox-lambda

Throwaway Lambda for validating the whole forecast → Provisioned Concurrency
pipeline before pointing anything at snip-infra. Has a configurable simulated
cold-start delay so pre-warming behavior is actually observable.

## Deploy

```bash
cd sandbox-lambda
terraform init
terraform plan     # read it -- check region, function name, IAM role
terraform apply
```

Grab the outputs:

```bash
terraform output function_name
terraform output function_url
```

## Verify it works

```bash
# should be slow the first time (cold start + SIMULATED_INIT_DELAY_SECONDS),
# fast on the next call within the same warm container
curl -s $(terraform output -raw function_url) | python3 -m json.tool
curl -s $(terraform output -raw function_url) | python3 -m json.tool
```

## Test Provisioned Concurrency manually, before your code touches it

```bash
FN=$(terraform output -raw function_name)

aws lambda put-provisioned-concurrency-config \
  --function-name "$FN" --qualifier prod \
  --provisioned-concurrent-executions 2 --region ap-south-1

# poll until Status is READY -- note the wall-clock time by eye first
aws lambda get-provisioned-concurrency-config \
  --function-name "$FN" --qualifier prod --region ap-south-1
```

Then run it through your own script instead of doing it by hand:

```python
from src.controller.provisioned_concurrency import set_provisioned_concurrency, wait_until_ready

set_provisioned_concurrency("sandbox-lambda", "prod", 2, region="ap-south-1")
elapsed = wait_until_ready("sandbox-lambda", "prod", region="ap-south-1")
print(f"Allocation took {elapsed:.1f}s")
```

Log the elapsed time in `docs/EXPERIMENT_LOG.md` and compare it against
`forecasting.lead_time_minutes` in `configs/experiment_config.yaml`.

## Tear down between sessions

Provisioned Concurrency bills continuously while allocated, even with zero
traffic. Delete the PC config after each test session:

```bash
aws lambda delete-provisioned-concurrency-config \
  --function-name "$FN" --qualifier prod --region ap-south-1
```

Full teardown when you're done with the sandbox entirely:

```bash
terraform destroy
```

## Notes

- `authorization_type = "NONE"` on the Function URL is deliberate for this
  throwaway sandbox so Locust can hit it directly with no API Gateway or
  auth setup. Do not reuse this pattern for snip-infra.
- `handler.py`'s delay runs at *module import time*, which is Lambda's actual
  cold-start path -- so a genuine cold start is slow and a reused warm
  container is fast, matching real behavior instead of faking it per-request.
