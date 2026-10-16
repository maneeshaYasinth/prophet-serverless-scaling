# loadgen: EC2 load generator and controller host

One EC2 instance in the same region as `sandbox-lambda` that runs Locust and
`live_controller.py`. It replaces the laptop as the load generator so results do
not depend on laptop power management or home network conditions (Known issues
1-3 in `docs/EXPERIMENT_LOG.md`).

- `c7i-flex.large`, non-burstable and Free-plan eligible (a `t3` would run out of CPU credits mid-run and throttle)
- No SSH key and no inbound port: shell access through AWS Session Manager
- IAM role limited to: invoking `sandbox-lambda`, setting its Provisioned
  Concurrency, reading CloudWatch metrics, and the results bucket
- Code comes from the public GitHub repo (`git pull` to update), so every run
  uses a known commit
- Results go to an S3 bucket; `terraform destroy` refuses while it holds data

Cost: about $0.08/h while running (ap-south-1 on-demand; drawn from Free plan
credits while they last), plus a few cents a
month for the 20 GiB disk while stopped. **Stop the instance between sessions.**

## One-time setup (laptop)

```bash
brew install --cask session-manager-plugin   # needed for `aws ssm start-session`
cd loadgen
terraform init
terraform plan     # review: 1 instance, 1 security group, 1 IAM role + policy, 1 S3 bucket
terraform apply
```

First boot installs Python and the requirements (about 5 minutes). It is ready
when `/opt/loadgen-ready` exists; progress is in `/var/log/loadgen-setup.log`.

## Each session

```bash
# laptop: start the instance and open a shell on it
aws ec2 start-instances --region ap-south-1 --instance-ids $(terraform -chdir=loadgen output -raw instance_id)
$(terraform -chdir=loadgen output -raw connect)

# instance: become ec2-user (venv activates automatically), update code, check the commit
sudo -iu ec2-user
git pull && git rev-parse --short HEAD
pip install -r requirements.txt   # only if requirements changed
```

Run long jobs inside `tmux` so they survive a dropped session
(`tmux new -s run`, detach with Ctrl-b d, reattach with `tmux attach -t run`):

```bash
# window 1: traffic (USER_RPS fixes the load per user, independent of latency)
RUN=$(date +%Y%m%d-%H%M)_seasonal_c2dry
TRAFFIC_PATTERN=seasonal DURATION_S=5700 SEED=42 USER_RPS=10 \
  SANDBOX_INVOKE_LOG=data/raw/$RUN.jsonl \
  locust -f src/data_generation/locust_scenarios/sandbox_locustfile_patterns.py --headless \
  --csv data/raw/$RUN --html data/raw/$RUN.html

# window 2 (Ctrl-b c): controller
python -m src.controller.live_controller --minutes 95
```

Afterwards, upload results from the instance, then download them on the laptop:

```bash
# instance
aws s3 sync data/raw s3://$RESULTS_BUCKET/data/raw
aws s3 sync results s3://$RESULTS_BUCKET/results

# laptop
aws s3 sync s3://$(terraform -chdir=loadgen output -raw results_bucket)/data/raw data/raw
aws s3 sync s3://$(terraform -chdir=loadgen output -raw results_bucket)/results results
```

Then stop the instance:

```bash
aws ec2 stop-instances --region ap-south-1 --instance-ids $(terraform -chdir=loadgen output -raw instance_id)
```

After any `--apply` run, check nothing is left billing:

```bash
aws lambda list-provisioned-concurrency-configs --function-name sandbox-lambda --region ap-south-1
```
