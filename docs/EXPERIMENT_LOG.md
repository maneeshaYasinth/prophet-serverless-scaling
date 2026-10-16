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

## Known issues

Open problems that affect the validity of results. Update the status when one is
resolved; details are in the run entries named.

| # | Issue | First seen | Status / mitigation |
|---|---|---|---|
| 1 | Laptop load generator throttled on battery with the display off: throughput capped at about 45 req/s regardless of users | 2026-10-10-3 | Resolved: Locust and the controller now run on EC2 (`loadgen/`, c7i-flex.large in ap-south-1); validated in 2026-10-16-1 |
| 2 | Single-process Locust saturates at high load (5x users gave 3.6x throughput; client P95 up while billed time flat) | 2026-10-04-1 | Partly mitigated: EC2 client; 20 users x 10 req/s delivered exactly 199.7 req/s. Still to check at spiky peak (100 users, about 1,000 req/s) |
| 3 | Network conditions vary between sessions (131 vs 225 req/s at 20 users) | 2026-10-06-1 | Resolved: same-region EC2 client plus `USER_RPS` (fixed requests per second per user) makes the load independent of latency. Still run conditions back-to-back |
| 4 | Sandbox stack missing at run time (destroyed between sessions), so every request failed | 2026-10-04-1, 2026-10-10-3 | Mitigated: keep the function deployed (idle cost is zero); invoke once and check Locust `# fails` = 0 before each run |
| 5 | `sandbox_user.py` appends to the invoke log, mixing runs in one file | 2026-10-04-1 | Mitigated: unique `SANDBOX_INVOKE_LOG` per run |
| 6 | `cold_start` flag counts environment inits, not user-visible cold starts (proactive initialisation hides most) | 2026-10-06-1 | Open. Decide the metric: report both, with a latency threshold (e.g. > 1 s) for user-visible |
| 7 | Capacity calibration evaluated in-sample, on a falling segment only | 2026-10-10-2 | Open. Recalibrate on a longer training run and evaluate on a separate run |
| 8 | `concurrency` as a Layer 1 regressor leaks future data unless lagged | 2026-10-06-1 | Open. Use lagged concurrency only |
| 9 | `TrafficPatternShape` spikes can overlap and merge at high `SPIKES_PER_HOUR` | 2026-10-04-1 | Open. Document in the method or enforce non-overlapping spikes |
| 10 | Controller trained on data from before the run (an earlier session plus zero-filled gap inside the fetch lookback) | 2026-10-16-2 | Resolved: `--history-start`, set by `run_experiment.sh` to the run's first full minute |

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

### Run: 2026-10-10-1
- Condition: vanilla-prophet (offline rolling-origin forecast evaluation; no AWS
  calls, no scaling actions)
- Traffic pattern: seasonal
- Data source: real CloudWatch+Locust (`data/processed/seasonal_train_run1.csv`
  from Run 2026-10-06-1, 89 full minutes)
- Duration / sample size: 20 forecast origins (18:38 -> 18:57 UTC) x 10 horizon
  steps = 200 forecasts
- Configuration (`configs/experiment_config.yaml`):
  - Training window W = 60 min (two full cycles), horizon H = 10 min
    (`lead_time_minutes`), step S = 1 min
  - Custom seasonality: period 30 min, Fourier order 3; built-in
    daily/weekly/yearly seasonality off; interval width 0.95; seed 42
  - At origin t the model is fitted on [t - W, t) only, so no future data leaks
    into training
- Results:
  - P95 / P99 latency, cold starts, cost: not applicable (forecast accuracy only)

    | Horizon | MAE (invocations/min) | MAPE | 95% interval coverage |
    |---|---|---|---|
    | 1 min | 355 | 2.23% | 95% |
    | 2-4 min | 371-389 | 2.40-2.58% | 90% |
    | 5 min | 207 | 1.65% | 95% |
    | 6-9 min | 144-161 | 1.45-1.50% | 95-100% |
    | 10 min | 176 | 1.59% | 95% |
  - Negative `yhat_lower`: 0% (vs about 100% on synthetic spiky data,
    Run 2026-09-07-1)
  - Mean interval width about 1,720-1,740 invocations/min at every horizon
- Notes / anomalies:
  - Outputs: `results/rolling_forecast/seasonal_train_run1_forecasts.csv`,
    `_summary.json`, `_forecast.png`. Reproducible: two runs gave
    byte-identical CSVs.
  - Error is higher at h = 1-4 than h = 5-10. This is not a real horizon effect:
    all 20 origins sit on one descending segment, so short-horizon targets fall
    on the steep drop just after the 18:36 peak. Too few origins to infer a
    horizon trend.
  - Near-best case for Prophet: near-sinusoidal traffic with a known period.
  - Small dips in actual traffic at about 17:58 and 18:32 UTC (e.g. 14,600 vs
    about 16,000 expected), probably client-side; candidates for testing the
    Layer 3 Z-score detector.
  - `aws.function_name` in the config changed from `snip-infra-handler` to
    `sandbox-lambda`.
- Next step: collect a longer seasonal training run (e.g. 3 h) for more origins
  across all phases of the cycle; convert forecasts to a Provisioned
  Concurrency target using the measured concurrency-vs-rate relationship.

### Run: 2026-10-10-2
- Condition: vanilla-prophet vs enhanced-prophet Layer 2 (offline capacity
  replay; no AWS calls, no scaling actions)
- Traffic pattern: seasonal
- Enhancement layers active (if enhanced-prophet): confidence-bound only
- Data source: real CloudWatch+Locust (`data/processed/seasonal_train_run1.csv`)
  and the 10-minute-ahead forecasts from Run 2026-10-10-1
- Duration / sample size: calibration on 89 minutes; replay on 20 minutes
  (18:38 -> 18:57 UTC)
- Configuration:
  - Conversion (`src/controller/capacity_model.py`):
    target = ceil(intercept + slope x req/s + headroom), with req/s =
    forecast invocations per minute / 60
  - Fitted: intercept 3.91, slope 0.0550 per req/s (about 1 environment per
    18 req/s), R^2 0.910; headroom 1.68 = 95th percentile of fit residuals
    (`capacity.calibration_quantile: 0.95`)
  - C2 feeds `yhat`, C3 feeds `yhat_upper` through the identical conversion
- Results:
  - P95 / P99 latency, cold starts, cost per request: not applicable (offline)

    | Target | Under-provisioned minutes | Env-minutes | Excess env-minutes |
    |---|---|---|---|
    | C2 (`yhat`) | 0 / 20 | 316 | 54 (mean +2.7 per minute) |
    | C3 (`yhat_upper`) | 0 / 20 | 332 | 70 (mean +3.5 per minute) |
    | Perfect forecast (actual rate) | 0 / 20 | 315 | 53 |
- Notes / anomalies:
  - Little's law (rate x billed duration) predicts about 1 concurrent
    environment, but CloudWatch measured 7-28, so an empirical calibration is
    used instead of an assumed formula.
  - With the 10% AWS buffer on top of the headroom (first pass), excess was 84
    (C2) / 102 (C3) env-minutes, about 30% over even with a perfect forecast.
    `aws.pc_buffer_percent` changed 10 -> 0: the measured headroom replaces the
    rule of thumb.
  - C2 is within one env-minute of a perfect forecast; C3 adds about 5%
    capacity with no under-provisioning to prevent on this segment.
  - Falling-traffic minutes sit below the fit line: concurrency may drop faster
    than request rate on the way down (possible hysteresis; not yet tested).
  - In-sample (calibrated and evaluated on the same run) and only covers a
    falling segment, so it cannot show under-provisioning on a rise.
  - Outputs: `results/capacity_calibration/seasonal_train_run1.json`,
    `_replay.csv`, `_calibration.png`.
- Next step: 3-hour seasonal training run plus a separate evaluation run, so
  calibration and replay are out-of-sample and cover rising slopes.

### Run: 2026-10-10-3 (FAILED: load generator throttled)
- Condition: vanilla-prophet, live dry run (`live_controller.py`, no `--apply`;
  decisions computed, Provisioned Concurrency never changed)
- Traffic pattern: seasonal (`TrafficPatternShape`, `SEED=42`, `DURATION_S=5700`)
- Data source: sandbox Lambda (redeployed with Terraform before the run, now
  version 6) via signed boto3 Invoke and Locust; controller reading CloudWatch
- Duration / sample size: 16:45:53 -> 18:05:25 UTC (stopped early), 397,130
  requests, 11 errors (`Read timeout`); 81 controller ticks (62 warming up,
  19 decisions, targets 7-11)
- Results:
  - Not valid as a seasonal test; no latency/cost results reported.
  - Cold start count: 21 (19 at start-up, as predicted after one manual invoke)
- Notes / anomalies:
  - First attempt (22:08 local) sent 68,521 requests that all failed with
    `ResourceNotFoundException`: the sandbox stack had been destroyed. Files
    deleted; stack redeployed with `terraform apply`.
  - Minutes 0-17: normal seasonal load (9,700-15,900 requests/min, about 9
    req/s per user, P95 131-158 ms).
  - From minute 18 (22:33:04 local) throughput capped at about 2,700
    requests/min (about 45 req/s) regardless of user count (9-31 users).
    Client P95 rose to 450-2,100 ms while billed duration stayed at 2 ms, so the
    bottleneck was the client, not Lambda.
  - Power log: on battery for the whole session; display turned off at
    22:33:04, the same minute the cap began. No sleep events and no gap in
    requests longer than 0.88 s, so the Mac did not sleep. Throughput stayed
    capped after the display came back on.
  - Likely cause: macOS power management throttling the background Locust
    process (inside VS Code's terminal) on battery once the display was off;
    `caffeinate -i` prevents sleep but not throttling. The 2026-10-06 run, on
    AC power, kept full throughput with the display off.
  - With flat post-drop data, Prophet's forecasts were unstable (`yhat`
    568-5,635/min) and targets low (7-11): the controller behaved consistently
    with its input, but the input was not seasonal.
  - Files kept: `data/raw/20261010-2215_*`,
    `results/controller/20261010-2215_c2_seasonal_dryrun.csv`.
- Next step: rerun on AC power with `caffeinate -dis`, checking throughput
  against user count in the first 20 minutes; or move Locust to an EC2 instance
  in ap-south-1 so the load generator is independent of laptop power settings
  and network.

### Run: 2026-10-16-1
- Condition: infrastructure validation (EC2 load generator; no scaling actions)
- Traffic pattern: steady (`TrafficPatternShape`, 20 users, `USER_RPS=10`)
- Data source: sandbox Lambda via signed boto3 Invoke from EC2 (`loadgen/`,
  c7i-flex.large, ap-south-1, commit `c45c23c`), plus a 2-minute
  `live_controller.py` dry run reading CloudWatch
- Duration / sample size: 120 s, 23,982 requests, 0 failures (after a 12 s
  aborted first attempt: 1,808 requests, 0 failures)
- Results:
  - Throughput: 199.7 req/s (= 20 users x 10 req/s, as configured)
  - P50 / P95 / P99 / P99.9 / max: 25 / 44 / 46 / 66 / 190 ms
  - Cold start count: none in the 120 s run (environments still warm from the
    aborted attempt a minute earlier, whose P99 of 3.3 s was its 20 start-up
    cold starts)
  - Cost per request: not computed (smoke test)
- Notes / anomalies:
  - Versus the laptop (2026-10-06-1, 20 users): median 92 -> 25 ms, P95
    122 -> 44 ms, P99 156 -> 46 ms. Warm latency now sits in a tight 25-46 ms
    band, so a 3 s cold start is far more visible in P99/P99.9.
  - The Free plan rejected `c6i.large` (not Free-tier eligible); used
    `c7i-flex.large`, which is non-burstable.
  - `Connection pool is full ... 169.254.169.254` warnings at start-up are
    harmless: 20 boto3 clients fetching IAM-role credentials from the instance
    metadata service at once.
  - Controller dry run: `train` 0 -> 1 -> 2, no permission errors, so
    `cloudwatch:GetMetricData` works from the instance role.
  - The instance clock and file timestamps are UTC.
- Next step: C2 live dry run, seasonal, 95 minutes, from EC2 with `USER_RPS=10`;
  then recalibrate the capacity model on EC2-generated data, because the client
  changed.

### Run: 2026-10-16-2
- Condition: vanilla-prophet, live dry run (decisions computed, Provisioned
  Concurrency never changed), first valid end-to-end run of the controller
- Traffic pattern: seasonal (`TrafficPatternShape`, `SEED=42`, `USER_RPS=10`,
  8-32 users, 30-minute period)
- Data source: EC2 load generator (c7i-flex.large, commit `879a6cd`) via
  `run_experiment.sh seasonal c2 dryrun 95`; CloudWatch export
  `data/raw/seasonal_c2dry_ec2_run1.csv` (trimmed copy in `data/processed/`)
- Duration / sample size: 95 min, 19:07:32-20:42 UTC, 1,156,490 requests,
  0 errors; 96 controller ticks (54 warming up, 42 decisions)
- Results:
  - P95 latency: 43.8 ms (P50 24.9, P99.9 60.9, max 3,425 ms)
  - P99 latency: 45.7 ms
  - Cold start count: 53 inits; 24 user-visible (> 1 s): all 20 start-up
    plus 4 of 33 mid-run
  - Cost per request: not computed (billed mean 6.0 ms)
  - Load accuracy: requests per minute 99.0-101.1% of users x 10 req/s;
    latency flat across 8-32 users (P95 42-44 ms), so no client bottleneck
  - CloudWatch vs Locust: 1,156,516 vs 1,156,490 invocations (+26)
  - Forecast accuracy (peak `yhat` over each decision's window vs actual):
    32 clean decisions MAPE 0.4% (worst 5.5%); 10 contaminated decisions MAPE
    14.1% (worst 39.9%)
- Notes / anomalies:
  - Bug found: the first 10 decisions (19:39-19:48) trained on a window
    reaching back to the EC2 smoke test at 18:36-18:39 plus 27 zero-filled
    minutes, so decisions started after 32 min instead of 63. Once those minutes
    left the fetch lookback the controller warmed up again until 20:11. Fixed
    with `--history-start` (Known issue 10); an offline replay reproduces the
    bug (first decision 19:39) and the fix (first decision 20:11).
  - Peak concurrency from EC2 is 5-18, against 7-28 from the laptop at the same
    user counts. The laptop calibration therefore over-provisions: its targets
    were 11-30, a mean excess of 7.8 environments.
  - In-sample EC2 fit: concurrency = 1.47 + 0.0432 x req/s (R^2 0.89),
    headroom 2.04; 2 of 39 decisions under-provisioned and mean excess 2.9 when
    applied to this run. Needs an out-of-sample check.
  - Mid-run inits again cluster on rising slopes (about 1,677-2,400 s,
    3,397-4,203 s, 5,102-5,636 s); 29 of 33 returned in 14-74 ms (proactive
    initialisation), matching 2026-10-06-1.
- Next step: switch `controller.calibration_file` to an EC2 calibration; run a
  second seasonal dry run to evaluate it out of sample; then the first
  `--apply` run.
