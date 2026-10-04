# Experiment Log

Log every run here, even failed/partial ones — the panel and your supervisor will want to see
iteration, not just final numbers. One entry per run.

## Template (copy for each new run)

### Run: YYYY-MM-DD-N

- **Condition:** reactive-baseline | vanilla-prophet | enhanced-prophet
- **Traffic pattern:** steady | spiky | seasonal
- **Enhancement layers active (if enhanced-prophet):** regressors / confidence-bound / z-score / adaptive-retrain
- **Data source:** synthetic | real CloudWatch+Locust
- **Duration / sample size:**
- **Results:**
  - P95 latency:
  - P99 latency:
  - Cold start count:
  - Cost per request:
- **Notes / anomalies:**
- **Next step:**

---

## Runs

### Run: 2026-09-07-1
- Condition: vanilla-prophet
- Traffic pattern: steady, spiky, seasonal (synthetic)
- Data source: synthetic
- Notes: initial Prophet fit via `prophet_starter.py`. Spiky pattern produced wide,
  negative-floored confidence intervals — concretely motivates the confidence-bound
  trigger layer (layer 2) in the enhanced framework.
- Next step: pull real CloudWatch/Locust data, replace synthetic generator.

### Run: 2026-09-16-1
- Condition: enhanced-prophet
- Traffic pattern: spiky (synthetic)
- Enhancement layers active (if enhanced-prophet): confidence-bound / z-score
- Data source: synthetic
- Duration / sample size: 150 holdout points
- Results:
  - Point-forecast capacity total: 300
  - Confidence-bound capacity total: 1057 (+252.3% vs point forecast)
  - Enhanced capacity total: 1122 (+274.0% vs point forecast)
  - Negative lower-bound forecasts: 100.0% of points
  - Layer 2 activations: 126 / 150 decisions
  - Layer 3 overrides: 24 / 150 decisions
- Notes / anomalies: The demo completed without errors and saved
  `testing/layer_validation/results/layer_comparison_spiky.png`. This synthetic demo does not measure P95/P99
  latency, cold starts, or cost per request.
- Next step: validate the layers against real CloudWatch/Locust data.

### Run: 2026-09-16-2
- Condition: vanilla-prophet
- Traffic pattern: steady, spiky, seasonal (synthetic)
- Data source: synthetic
- Duration / sample size: 48 hours per pattern, 576 points per pattern at 5-minute intervals
- Results:
  - Generated `steady_traffic.csv`, `spiky_traffic.csv`, and `seasonal_traffic.csv`
    under `testing/pattern_exploration/data/processed/`.
  - Prophet forecast plots generated for all three traffic patterns under
    `testing/pattern_exploration/results/`.
- Notes / anomalies: This run prepares reproducible local input data and visual
  forecast outputs. It does not measure P95/P99 latency, cold starts, or cost per
  request.
- Next step: use the generated data as the common input for the three scaling
  conditions before moving to real CloudWatch/Locust data.

### Run: 2026-09-16-3
- Condition: enhanced-prophet
- Traffic pattern: spiky (synthetic)
- Enhancement layers active (if enhanced-prophet): confidence-bound / z-score
- Data source: synthetic
- Duration / sample size: 150 holdout points
- Results:
  - Point-forecast capacity total: 300
  - Confidence-bound capacity total: 1052 (+250.7% vs point forecast)
  - Enhanced capacity total: 1120 (+273.3% vs point forecast)
  - Negative lower-bound forecasts: 100.0% of points
  - Layer 2 activations: 126 / 150 decisions
  - Layer 3 overrides: 24 / 150 decisions
- Notes / anomalies: A rerun of the demo completed successfully and saved
  `testing/layer_validation/results/layer_comparison_spiky.png`. Capacity totals vary slightly between Prophet
  runs because of numerical variation in Stan fitting. This synthetic demo does
  not measure P95/P99 latency, cold starts, or cost per request.
- Next step: validate cold-start and latency impact using the same workloads on
  the real Lambda application.

### Run: 2026-09-16-4
- Condition: vanilla-prophet and enhanced-prophet local validation
- Traffic pattern: steady, spiky, seasonal for pattern exploration; spiky for
  layer validation
- Enhancement layers active (if enhanced-prophet): confidence-bound / z-score
- Data source: synthetic
- Duration / sample size: 576 points per traffic pattern; 150 holdout points for
  the Layer 2/3 demo
- Results:
  - Reorganized local testing into `testing/pattern_exploration/` for vanilla
    Prophet behavior and `testing/layer_validation/` for enhancement-layer
    validation.
  - Moved generated CSV inputs and forecast plots into the corresponding testing
    environment directories.
  - Updated both scripts to resolve imports and output paths from their own file
    locations, so they run from the repository root.
  - Pattern exploration completed for all three traffic shapes.
  - Layer validation completed successfully with 100.0% negative lower bounds,
    126 Layer 2 activations, and 24 Layer 3 overrides.
- Notes / anomalies: The local validation measures forecast and capacity behavior
  only. It does not yet measure AWS Lambda P95/P99 latency, cold starts, or cost
  per request.
- Next step: run the same separated workflows against real CloudWatch/Locust
  data and connect the validated controller to Lambda Provisioned Concurrency.

### Run: 2026-09-28-1
- Condition: reactive-baseline
- Traffic pattern: steady
- Data source: sandbox Lambda via signed boto3 Invoke and Locust
- Duration / sample size: default steady shape, 9,611 successful requests
- Results:
  - P95 latency: 165.15 ms
  - P99 latency: 273.21 ms
  - Cold start count: 17
  - Cost per request: approximately $2.2e-7
- Notes / anomalies: The per-request source log is stored in
  `results/reactive_baseline_steady_log.jsonl`, with the canonical summary in
  `results/reactive-baseline_steady.json`. Latency includes signed boto3 and
  network overhead. This is a sandbox pipeline measurement, not a final
  `snip-infra` or Function URL result. The baseline runner now supports steady,
  spiky, and seasonal shapes; only steady has been run and recorded here.
- Next step: run the same baseline for spiky and seasonal traffic, then repeat
  the workloads with vanilla and enhanced Prophet control.

### Run: 2026-09-28-2
- Condition: infrastructure measurement
- Traffic pattern: not applicable
- Data source: sandbox Lambda Provisioned Concurrency API
- Duration / sample size: three allocation changes on alias `prod` in `ap-south-1`
- Results:
  - 0 -> 2 provisioned instances: 84.3 seconds
  - 2 -> 5 provisioned instances: 84.4 seconds
  - 5 -> 2 provisioned instances: 12.5 seconds
  - All changes reached `READY`
- Notes / anomalies: `measure_pc_lag.py` removes the Provisioned Concurrency
  configuration in a `finally` block. These samples support the configured
  `forecasting.lead_time_minutes: 10`, but they are limited to this sandbox and
  these capacity values; more repetitions are needed for a robust lag
  distribution.
- Next step: collect repeated lag measurements and include Provisioned
  Concurrency cost in the proactive-condition comparison.

### Run: 2026-10-04-1
- Condition: reactive-baseline (smoke test of the new traffic-pattern harness;
  no Provisioned Concurrency)
- Traffic pattern: spiky (`TrafficPatternShape`, `SEED=42`, `BASE_USERS=20`,
  `SPIKES_PER_HOUR=24`, `DURATION_S=300`)
- Data source: sandbox Lambda via signed boto3 Invoke and Locust
  (`sandbox_locustfile_patterns.py`, same `LambdaInvokeUser` as 2026-09-28-1)
- Duration / sample size: 300 s (12:30:32-12:35:32 +05:30), 83,863 successful
  requests, 0 errors
- Results:
  - P95 latency: 340 ms
  - P99 latency: 561 ms
  - Cold start count: 93 (0.11%); 19 at start-up, 74 at spike onset, all within
    the first 57 s; cold-start latency 2.6-3.7 s (median 3.16 s)
  - Cost per request: approximately $2.2e-7 (mean billed duration 9 ms, 128 MB)
  - Per phase:

    | Phase | Users | req/s | P95 | P99 | Cold starts |
    |---|---|---|---|---|---|
    | Pre-spike (0-49.5 s) | 20 | 131 | 241 ms | 392 ms | 19 |
    | Spike (49.5-176.6 s) | 100 | 476 | 360 ms | 616 ms | 74 |
    | Post-spike (176.6-300 s) | 20 | 137 | 250 ms | 372 ms | 0 |
- Notes / anomalies:
  - Raw log: `data/raw/smoke_spiky.jsonl` (gitignored). It also contains 16,420
    rows from an earlier failed attempt (12:26:55-12:27:58, all
    `ResourceNotFoundException: Function not found`), because `sandbox_user.py`
    appends to the log. Those rows are excluded from the figures above.
  - The two seeded spikes (49.5-122.9 s and 115.1-176.6 s) overlapped and merged
    into one 127 s spike. Likely only at a high `SPIKES_PER_HOUR` relative to
    `DURATION_S`.
  - Possible load-generator bottleneck: 5x users gave only 3.6x throughput, and
    response P95 rose 241 -> 360 ms while billed duration P95 stayed at
    15-16 ms. The added tail latency is outside Lambda (client CPU or network),
    so single-process Locust may confound spike tail latency.
  - 19 (not 20) start-up cold starts because a manual `aws lambda invoke` just
    before the run had already warmed one environment.
- Next step: use a unique `SANDBOX_INVOKE_LOG` per run; re-run with
  `--processes 4` (or fewer users) to check whether spike P95 drops back toward
  the pre-spike level; decide whether `TrafficPatternShape` replaces the shapes
  in `shapes.py` for all nine scenarios.
