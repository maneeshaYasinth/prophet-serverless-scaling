# Enhanced Prophet-Based Proactive Auto-Scaling for Serverless Architectures

Final-year dissertation project (BSc Hons Electronics and Computer Science, University of Kelaniya).
Supervisor: Dhanushka Jayasuriya. Target venue: ICTER 2026.

## Problem

AWS Lambda has no persistent server history, so standard reactive/threshold-based autoscaling
reacts *after* a traffic spike starts, causing cold starts and tail-latency (P95/P99) spikes.
AWS's own Predictive Scaling product does not cover Lambda (only EC2/ECS). This project builds
an enhanced Prophet forecasting framework that proactively pre-warms AWS Lambda capacity via
Provisioned Concurrency, ahead of predicted demand.

Test application: `snip-infra` (a URL shortener on AWS Lambda).

## Experimental design

3 conditions × 3 traffic patterns = 9 scenarios.

| | Steady | Spiky | Seasonal |
|---|---|---|---|
| **Reactive baseline** (AWS default autoscaling) | | | |
| **Vanilla Prophet** | | | |
| **Enhanced Prophet** (4 layers below) | | | |

Metrics recorded per scenario: tail latency (P95/P99), cold start count, cost per request.

## The four enhancement layers (core contribution)

1. **Custom CloudWatch regressors** — feed exogenous infra signals into Prophet via `add_regressor()`.
2. **Confidence-bound scaling triggers** — scale to `yhat_upper`, not `yhat`, to avoid under-provisioning.
3. **Z-score residual anomaly detection** — emergency override when residuals exceed ±2σ.
4. **Adaptive retraining** — sliding-window refit to prevent model drift.

## Repo layout

```
src/
  data_generation/     Locust load-generation scripts for steady/spiky/seasonal traffic
  baseline/            Reactive autoscaling baseline (condition 1)
  forecasting/         Vanilla Prophet (condition 2) + enhanced Prophet layers (condition 3)
  controller/          Separate process: calls Provisioned Concurrency API based on forecast output
  evaluation/          Metrics collection + comparison across the 9 scenarios
data/
  raw/                 Raw CloudWatch/Locust exports
  processed/           Cleaned ds/y(+regressor) dataframes ready for Prophet
notebooks/             Exploratory analysis, plots for the dissertation
results/               Per-scenario metrics output (P95/P99, cold starts, cost)
configs/               Experiment configuration (traffic pattern params, thresholds)
measure_pc_lag.py      Measure Provisioned Concurrency allocation time on the sandbox
docs/
  EXPERIMENT_LOG.md    Running log of every experiment run — fill this in as you go
testing/
  pattern_exploration/  Vanilla Prophet behavior on steady/spiky/seasonal traffic
  layer_validation/     Layer 2/3 validation on synthetic spiky traffic
```

## Status

Currently at: Layers 2 and 3 are implemented and validated on synthetic spiky
traffic data. A sandbox reactive-baseline measurement pipeline is now also in
place: Locust generates the three traffic patterns, a signed boto3 Invoke call
targets the throwaway Lambda, and per-request JSONL logs are summarized into
scenario metrics. Provisioned Concurrency allocation lag has been measured on
the sandbox as part of validating the required forecast lead time.

Next: repeat the baseline for spiky and seasonal traffic, then run the vanilla
and enhanced Prophet conditions against the same sandbox workloads before
swapping in real CloudWatch/Locust data. Layer 1 (regressors), layer 4
(adaptive retraining), and the live forecast-to-controller loop remain future
work.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run the local testing environments from the repository root:

```bash
python testing/pattern_exploration/synthetic_traffic.py
python testing/pattern_exploration/explore_prophet.py
python testing/layer_validation/demo_layers_on_synthetic_data.py
```

Run the sandbox reactive baseline from the repository root after deploying
`sandbox-lambda` and configuring valid AWS credentials:

```bash
python -m src.baseline.reactive_autoscaling steady
python -m src.baseline.reactive_autoscaling spiky
python -m src.baseline.reactive_autoscaling seasonal
```

Use `SHAPE_RUN_TIME=60` before a command for a short smoke test. The default
durations are 600 seconds for steady, 1,800 seconds for spiky, and 3,600
seconds for seasonal traffic. Raw invocation logs are written to
`results/reactive_baseline_<pattern>_log.jsonl`; summarized results are written
to `results/reactive-baseline_<pattern>.json`.

The current sandbox baseline uses signed boto3 Lambda Invoke calls rather than
the Function URL. Its latency includes AWS SDK and network overhead, so these
measurements are pipeline validation rather than final `snip-infra` results.

## Open design questions (tracked honestly, not hidden)

- Is the Prophet forecast horizon long enough to cover Provisioned Concurrency allocation time?
  `put_provisioned_concurrency_config` does not allocate instantly — status returns `IN_PROGRESS`
  and ramp-up takes real time. The lead time chosen for forecasting must exceed this.
  The sandbox measurements in `docs/EXPERIMENT_LOG.md` currently show roughly 84 seconds for
  scale-up, compared with the configured 10-minute lead time.
