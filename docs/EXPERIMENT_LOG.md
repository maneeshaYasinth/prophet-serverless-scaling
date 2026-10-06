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

### Run: 2026-10-06-1
- Condition: reactive-baseline (Prophet training-data collection; no
  Provisioned Concurrency, confirmed empty with
  `list-provisioned-concurrency-configs` before the run)
- Traffic pattern: seasonal (`TrafficPatternShape`, `SEED=42`, `BASE_USERS=20`,
  amplitude +/-60% so 8-32 users, `SEASON_PERIOD_S=1800`, `DURATION_S=5400`)
- Data source: sandbox Lambda via signed boto3 Invoke and Locust
  (`sandbox_locustfile_patterns.py`, single process), plus CloudWatch via
  `cloudwatch_fetch.py`
- Duration / sample size: 5400 s, 2026-10-06 22:58:51 -> 2026-10-07 00:28:51
  +05:30 (17:28:51 -> 18:58:51 UTC), 1,123,469 requests, 0 errors
- Results:
  - P95 latency: 122 ms (P50 92 ms, P99.9 260 ms, max 3.63 s)
  - P99 latency: 156 ms
  - Cold start count: 51 (`cold_start: true`; 0.0045%), 20 at start-up and 31
    during the run
  - Cost per request: approximately $2.1e-7 (mean billed duration 5.4 ms, 128 MB)
  - Per-minute invocations by cycle:

    | Cycle | Mean /min | Peak /min (minute) | Trough /min (minute) |
    |---|---|---|---|
    | 1 | 12,347 | 19,389 (6) | 5,286 (22) |
    | 2 | 12,454 | 19,416 (36) | 5,336 (52) |
    | 3 | 12,644 | 19,981 (67) | 5,400 (82) |
- Notes / anomalies:
  - Files: raw log `data/raw/20261006-2258_seasonal_train.jsonl`; CloudWatch
    export `data/raw/seasonal_train_run1.csv` (91 rows, `--minutes 100`);
    trimmed Prophet input `data/processed/seasonal_train_run1.csv` (89 full
    minutes, 17:29 -> 18:57 UTC, partial first and last minutes dropped). All
    gitignored. `ds` is tz-naive UTC.
  - CloudWatch validation: total invocations 1,123,550 (CloudWatch) vs
    1,123,469 (Locust), +81 (0.007%), probably manual CLI invokes. Per full
    minute the difference is -0.19% to +0.18% (minute-boundary timing), so
    CloudWatch `Invocations` is a valid target series for Prophet.
  - No load-generator bottleneck: throughput stayed at about 10-11 req/s per
    user from 8 to 32 users (peak about 327 req/s), P95 109-138 ms at every user
    level, billed P95 15-16 ms throughout.
  - Cold starts recur on each rising slope (about 464-571 s, 1535-1994 s,
    3380-3935 s, 5248-5380 s): environments reclaimed in the trough are
    re-created on the next rise. This is a periodic, forecastable cold-start
    cost.
  - Only 5 of the 31 mid-run cold starts were visible to the client (3142,
    2087, 1774, 1009, 460 ms); the other 26 returned in 70-180 ms despite a
    billed duration of about 3.1 s. Likely Lambda proactive initialisation
    (init runs before the request arrives, init time billed to the first
    invoke). The 20 start-up cold starts all waited about 3.6 s. The
    `cold_start` flag therefore counts environment inits, not user-visible
    cold starts.
  - Throughput per user was higher than in 2026-10-04-1 (about 225 vs 131
    req/s at 20 users), so network/client conditions vary between sessions.
  - Regressors: `concurrency` correlates 0.954 with `y` and is not known in
    advance, so it can only be used lagged (leakage risk); `duration_ms` is
    nearly flat (3.7-5.6 ms).
- Next step: fit vanilla Prophet (C2) on the trimmed file with a custom
  30-minute seasonality (built-in daily/weekly off) and a rolling 10-minute-ahead
  forecast; define the cold-start metric as both inits and user-visible cold
  starts (e.g. latency > 1 s); run C1/C2/C3 for a pattern back-to-back in one
  session; add `--csv`/`--html` to future Locust runs.
