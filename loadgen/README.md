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
credits while they last), plus about $1.60-1.80 a month for the 20 GiB gp3
disk, which is kept while the instance is stopped. **Stop the instance between
sessions**, and destroy the stack once the final results are collected:
download results, empty the bucket (`aws s3 rm s3://<bucket> --recursive`),
then `terraform destroy` here and in `sandbox-lambda/`.

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
# laptop: start the instance and land in a shell as ec2-user (venv active, in the repo)
loadgen/session.sh start

# instance: update code, then start a run (returns after a 60 s health check)
git pull && git rev-parse --short HEAD
loadgen/run_experiment.sh seasonal c2 dryrun 95

# optional: watch it (detach with Ctrl-b d; the run keeps going)
tmux attach

# leave the instance (exit), close the laptop if you like; the run uploads to S3 when done

# laptop, after the run: download results, then stop the instance
loadgen/session.sh results
loadgen/session.sh stop
```

`loadgen/session.sh status` shows the instance state and any Provisioned
Concurrency still allocated; `stop` warns if any is.

### Run modes

| Command | Condition |
|---|---|
| `run_experiment.sh PATTERN c1 traffic` | C1 reactive baseline: Locust only |
| `run_experiment.sh PATTERN c2 dryrun` | Controller decides, Provisioned Concurrency untouched |
| `run_experiment.sh PATTERN c2 apply` | C2: controller sets Provisioned Concurrency from `yhat` |
| `run_experiment.sh PATTERN c3-layer2 apply` | C3 (Layer 2 only so far): from `yhat_upper` |

Each run is named `UTCDATE-TIME_PATTERN_CONDITION_MODE` and writes
`data/raw/RUN.jsonl` (+ Locust `.csv`/`.html`), `data/raw/RUN.meta.json`
(commit, settings, instance type) and `results/controller/RUN.csv`.
`USER_RPS` (default 10) and `SEED` (default 42) can be overridden as
environment variables. Preflight refuses to start if Provisioned Concurrency is
already allocated or another tmux session is running; the run is killed if
more than 1% of requests fail in the first minute.
