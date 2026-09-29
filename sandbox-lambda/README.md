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
# Run from the repository root. The default Function URL auth is AWS_IAM, so
# use a signed boto3 Invoke call rather than anonymous curl.
cd ..
python test_invoke.py
python test_invoke.py
```

The first call should report `cold_start: true` and take a little over the
configured three-second initialization delay. The second call should reuse the
warm execution environment. If you explicitly deploy with
`-var='function_url_auth_type=NONE'`, the Function URL can also be called with
`curl`, but that is not the path used by the baseline measurement pipeline.

## Run the reactive baseline

From the repository root, after deployment and with valid AWS credentials:

```bash
python -m src.baseline.reactive_autoscaling steady
python -m src.baseline.reactive_autoscaling spiky
python -m src.baseline.reactive_autoscaling seasonal
```

The baseline invokes the Lambda through signed boto3 calls and uses the shared
Locust shapes. Default durations are 600 seconds for steady, 1,800 seconds for
spiky, and 3,600 seconds for seasonal traffic. Use `SHAPE_RUN_TIME=60` for a
short smoke test. Each run writes raw per-request data to
`results/reactive_baseline_<pattern>_log.jsonl` and a summary to
`results/reactive-baseline_<pattern>.json`.

The checked-in steady sandbox run recorded 9,611 successful requests, 17 cold
starts, P95 of 165.15 ms, P99 of 273.21 ms, and approximately $2.2e-7 per
request. These latency values include boto3 and network overhead and should not
be treated as final `snip-infra` results.

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

The checked-in sandbox measurements were 84.3 seconds for 0 -> 2, 84.4 seconds
for 2 -> 5, and 12.5 seconds for 5 -> 2. All reached `READY`. Run
`python measure_pc_lag.py` from the repository root to repeat the measurement;
the script cleans up the PC configuration in a `finally` block.

## Tear down between sessions

Provisioned Concurrency bills continuously while allocated, even with zero
traffic. Delete the PC config after each test session:

```bash
aws lambda delete-provisioned-concurrency-config \
  --function-name "$FN" --qualifier prod --region ap-south-1
```

Confirm that the alias has no remaining Provisioned Concurrency configuration
before destroying the infrastructure. Provisioned Concurrency is created
out-of-band by the AWS CLI or Python and is not managed as a Terraform
resource, so run the commands in this order:

1. Delete Provisioned Concurrency.
2. Confirm it is gone with `aws lambda get-provisioned-concurrency-config`.
3. Run `terraform destroy`.

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
