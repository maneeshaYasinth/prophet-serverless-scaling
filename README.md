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
docs/
  EXPERIMENT_LOG.md    Running log of every experiment run — fill this in as you go
testing/
  pattern_exploration/  Vanilla Prophet behavior on steady/spiky/seasonal traffic
  layer_validation/     Layer 2/3 validation on synthetic spiky traffic
```

## Status

Currently at: Layers 2 and 3 are implemented and validated on synthetic spiky
traffic data. Layer 2 uses the upper confidence bound for capacity decisions,
while Layer 3 applies a Z-score residual anomaly override. Vanilla Prophet still
produces wide, negative-floored confidence intervals on spiky traffic, motivating
the confidence-bound trigger.

Next: swap synthetic data for real CloudWatch/Locust data, then build layer 1
(regressors) and layer 4 (adaptive retraining), in parallel with standing up the
reactive baseline scenario.

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

## Open design questions (tracked honestly, not hidden)

- Is the Prophet forecast horizon long enough to cover Provisioned Concurrency allocation time?
  `put_provisioned_concurrency_config` does not allocate instantly — status returns `IN_PROGRESS`
  and ramp-up takes real time. The lead time chosen for forecasting must exceed this.
