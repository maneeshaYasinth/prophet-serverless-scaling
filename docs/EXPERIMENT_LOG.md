# Experiment Log

Log every run here, even failed/partial ones — the panel and your supervisor will want to see
iteration, not just final numbers. One entry per run.
Figures are embedded under the run that produced them, each with how to read it and what
it shows (view in the Markdown preview or on GitHub).

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
| 2 | Single-process Locust saturates at high load (5x users gave 3.6x throughput; client P95 up while billed time flat) | 2026-10-04-1 | Resolved (2026-11-04-1): `run_experiment.sh` runs Locust with `--processes 2` (`LOCUST_PROCESSES`, recorded in meta.json). A single process on c7i-flex.large topped out at about 880 req/s (80.4% of the spike target, 2026-11-03-2); with two, spikes reach 95.3% of target (peak 1,364 req/s) and spike P99 fell from 209.9 to 80.0 ms. The remaining ~5% shortfall is the ramp at spike onsets |
| 3 | Network conditions vary between sessions (131 vs 225 req/s at 20 users) | 2026-10-06-1 | Resolved: same-region EC2 client plus `USER_RPS` (fixed requests per second per user) makes the load independent of latency. Still run conditions back-to-back |
| 4 | Sandbox stack missing at run time (destroyed between sessions), so every request failed | 2026-10-04-1, 2026-10-10-3 | Mitigated: keep the function deployed (idle cost is zero); invoke once and check Locust `# fails` = 0 before each run |
| 5 | `sandbox_user.py` appends to the invoke log, mixing runs in one file | 2026-10-04-1 | Mitigated: unique `SANDBOX_INVOKE_LOG` per run |
| 6 | `cold_start` flag counts environment inits, not user-visible cold starts (proactive initialisation hides most) | 2026-10-06-1 | Open. Decide the metric: report both, with a latency threshold (e.g. > 1 s) for user-visible |
| 7 | Capacity calibration evaluated in-sample, on a falling segment only | 2026-10-10-2 | Partly mitigated (2026-10-29-1): pooled fit on EC2 runs 1 + 2 (80-400 req/s) with a multiplicative margin; leave-one-run-out shows no margin fixes extrapolation, so the calibration data must cover the experiment's load range. Held-out run 3 (2026-10-29-5): live decisions 0/29 under (old calibration 6/29) at +17% env-minutes, but concurrency per req/s drifts upward between sessions (17% of minutes above the margin). Candidate fix: recalibrate online from the live 60-minute window |
| 8 | `concurrency` as a Layer 1 regressor leaks future data unless lagged | 2026-10-06-1 | Open. Use lagged concurrency only |
| 9 | `TrafficPatternShape` spikes can overlap and merge at high `SPIKES_PER_HOUR` | 2026-10-04-1 | Open. Document in the method or enforce non-overlapping spikes |
| 10 | Controller trained on data from before the run (an earlier session plus zero-filled gap inside the fetch lookback) | 2026-10-16-2 | Resolved: `--history-start`, set by `run_experiment.sh` to the run's first full minute; confirmed live in 2026-10-18-5 (first decision at minute 64) |
| 11 | Seasonal traffic from EC2 is a near-exact repeating sine (fixed per-user rate, no noise), so a trivial seasonal-naive forecast beats Prophet 3x; the forecasting comparison is too easy to be meaningful | 2026-10-18-2 | Mitigated: seeded noise and drift in `TrafficPatternShape` (`traffic_realism` in the config); Prophet skill over seasonal naive +0.22 in simulation (2026-10-18-3) and +0.21 live (2026-10-18-5). Real Azure Functions trace planned before the thesis |
| 12 | Start state not controlled: a run started minutes after earlier traffic finds environments already warm, so it has no start-up cold starts (0 in 2026-10-18-5 vs 20 in 2026-10-16-2) | 2026-10-18-5 | Fixed (2026-10-30-1): `run_experiment.sh` publishes a fresh Lambda version and moves alias `prod` to it before every run, so no environment is warm; the version is recorded in each meta file (`lambda_version`, `start_state`). Validation run: 23 cold starts, all in the first 10 s, none after. Seen again in 2026-10-29-5 |
| 13 | A run started on stale code after `git pull` failed on the instance | 2026-10-18-4 | Resolved: `run_experiment.sh` refuses to start unless HEAD equals `origin/main`; since `7e439d5` it fast-forwards itself, moving clashing untracked results to `~/stash` |
| 14 | Re-targeting Provisioned Concurrency every minute stalls scale-up: each new `put` restarts an allocation that needs about 84 s, so the config stays IN_PROGRESS and the added environments never take traffic (usable PC stuck at 9 while the API reported 10-22) | 2026-11-01-1 | Fixed (2026-11-02-1, live): usable PC now follows the configured value on every ramp (was stuck at 9). Fix written and replayed in 2026-11-01-2: `controller.scale_up_policy: wait_for_ready` raises PC only when the config is READY (or none), to the peak over the longer window a raise stays in charge; lowers apply at once unless mid-raise above the usable count. Replay: minutes with usable PC short 2/29 vs 10/29 (held-out run 3) |
| 15 | Cold-start flag overstates user impact: provisioned environments flag their first request cold (no wait), and Lambda's proactive initialisation makes many on-demand inits fast too | 2026-11-01-1 | Mitigated: handler logs `init_type` (commit `7e439d5`); report user-visible cold starts (response > 1 s) as the primary count, with on-demand inits alongside |
| 16 | PC allocation time varies: raises took 1-5 min to reach READY (median 2; 7 of 19 took 3 min or more), longer than `pc_ready_minutes: 2`; small raises right after another change took 5 min twice | 2026-11-02-1 | Open: consider pc_ready 3, which needs `lead_time_minutes` 11 for the raise window |
| 17 | Spillover to on-demand environments with provisioned ones free: 25-48% of invocations spilled in minutes where PC utilisation peaked below 1.0. Mostly served by warm on-demand environments, so not cold starts, but it means PC is not the only capacity serving traffic | 2026-11-01-1 | Open: observed, cause not confirmed; report spillover alongside cold starts |
| 18 | Visible cold-start counts vary a lot between sessions under identical conditions: minutes 0-63 (same traffic, no PC in either run) gave 3 mid-run visible cold starts in 2026-11-03-1 and 13 in 2026-11-02-1 | 2026-11-03-1 | Open: single runs cannot separate conditions on counts this small; needs replicate runs, or a pattern with more cold starts, or both. Compare conditions with the warm-up period as a within-run control |
| 19 | Client latency inside spikes rises whenever PC is allocated: in-spike P95 ~101 ms in C2 and C3 against 60.5 ms in C1 (PC period), outside spikes unchanged (46-47 ms), warm-up (no PC) unchanged. In C3 the rise is the same for requests served by provisioned and by on-demand environments, and in spikes with almost no spillover, so it is not spillover. Billed duration is unchanged (median 2 ms), so the extra time is outside the function (invoke path at ~1,000 req/s with PC on the alias is the likely place, not confirmed). Not controller CPU (one Prophet step ~0.05 s) | 2026-11-04-3 | Open (2026-11-06-1): affects P95/P99 for every PC condition under spiky load. A diagnostic run with static PC (no controller) would show whether PC alone causes it |

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
- Figure:

  ![Provisioned capacity under three strategies, synthetic spiky traffic](../testing/layer_validation/results/layer_comparison_spiky.png)

  *Provisioned capacity (in requests/s) for point-forecast (orange), confidence-bound
  (blue) and Layer 2+3 (green dashed) scaling; black dots are actual traffic.*
  - How to read it: a line above the dots is spare capacity (cost); a dot above
    the line is unserved demand (cold starts).
  - What it shows: `yhat` (orange) sits at about 20 req/s, so every spike at about
    80 req/s is unserved. `yhat_upper` (blue) covers 70 req/s all the time, which
    is 7x the normal load. Layer 3 (green) jumps to about 110 when a spike is
    detected, but only after it has started. The blue line sits under the green
    one wherever the two agree. Synthetic data only.
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
- Figure:

  ![Vanilla Prophet forecast on synthetic spiky traffic](../testing/pattern_exploration/results/spiky_forecast.png)

  *Vanilla Prophet fit on 48 h of synthetic spiky traffic. Black dots are
  observations, the line is `yhat`, the shaded band is the 95% interval.*
  (`steady_forecast.png` and `seasonal_forecast.png` in the same folder.)
  - What it shows: Prophet cannot place short random spikes in time, so it
    averages them: `yhat` (about 20) sits above the normal level (about 10)
    and far below the spikes (about 80), and the band spans -25 to 65. A
    negative lower bound is meaningless for a request count. This is the
    motivation for Layer 3 (detect spikes rather than forecast them).
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
- Figure:

  ![Walk-forward Prophet forecast, laptop seasonal run](../results/rolling_forecast/seasonal_train_run1_forecast.png)

  *(a) Actual invocations per minute (blue) and the 10-minute-ahead forecast
  (orange, 95% band shaded) from each origin. (b) Mean absolute percentage
  error by forecast horizon.*
  - How to read it: forecasts start at the dashed line, once 60 minutes of
    history exist. Each orange point was made 10 minutes before that time,
    using only earlier data.
  - What it shows: the forecast follows the falling and rising slope within
    about 2%, and the actual line stays inside the band. The higher error at
    1-4 minutes comes from the steep drop just after the peak, not a real
    horizon effect (see notes).
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
- Figure:

  ![Capacity calibration, laptop seasonal run](../results/capacity_calibration/seasonal_train_run1_calibration.png)

  *(a) Peak concurrency per minute against request rate, with the least-squares
  line and line + headroom. (b) What C2 (`yhat`) and C3 (`yhat_upper`) would have
  provisioned from 10-minute-ahead forecasts, against actual concurrency.*
  - How to read it: (a) is the conversion rule: read a forecast rate on the x
    axis and go up to the dashed line to get the target. In (b), target above
    actual = no cold starts but extra cost.
  - What it shows: concurrency rises almost linearly with load (R^2 0.91), so a
    measured rule replaces Little's law, which predicts about 1. Both targets
    stay above actual in all 20 minutes; C3 is one environment above C2 most of
    the time. In-sample and on a falling segment only.
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

### Run: 2026-10-18-1
- Condition: capacity recalibration on EC2 data (offline; no AWS calls)
- Traffic pattern: seasonal
- Data source: `data/processed/seasonal_c2dry_ec2_run1.csv` (Run 2026-10-16-2)
- Duration / sample size: fit on 94 minutes; replay on 25 forecast origins
- Results:
  - Fit: concurrency = 1.47 + 0.0432 x req/s (R^2 0.893), headroom 2.04
    (95th percentile of residuals), buffer 0%
  - Prophet walk-forward on this run: MAPE 0.21-0.30% per horizon, 95% band
    coverage 80-100% (mean 90%), band width about 86 invocations/min
  - Replay (in-sample): C2 1/25 minutes under-provisioned, 69 excess
    env-minutes; C3 1/25, 71; perfect forecast 1/25, 68
- Notes / anomalies:
  - `controller.calibration_file` now points at
    `results/capacity_calibration/seasonal_c2dry_ec2_run1.json`; the laptop
    calibration over-provisioned by about 8 environments on EC2.
  - 1 short minute in 25 even with a perfect forecast is expected from a
    95th-percentile headroom.
  - Still in-sample: the next EC2 dry run is the out-of-sample check.
- Figures:

  ![Walk-forward Prophet forecast, EC2 seasonal run 1](../results/rolling_forecast/seasonal_c2dry_ec2_run1_forecast.png)

  *Same layout as Run 2026-10-10-1, on the first EC2 run.*
  - What it shows: EC2 traffic is a near-perfect sine (fixed requests per user,
    no network noise), so the forecast lies on top of the actual line, the
    band is too narrow to see, and the error is 0.2-0.3%. This "too easy"
    traffic led to Known issue 11.

  ![Capacity calibration, EC2 seasonal run 1](../results/capacity_calibration/seasonal_c2dry_ec2_run1_calibration.png)

  *Same layout as Run 2026-10-10-2, on EC2 data.*
  - What it shows: from EC2 the line is lower (5-18 environments vs 7-28 from
    the laptop), which is why the laptop calibration was replaced. In (b) C2
    and C3 overlap except at 20:28-20:30, because the band is so narrow. One
    minute (20:17) is under-provisioned, as expected from a 95% headroom.
- Next step: second seasonal dry run with this calibration.

### Run: 2026-10-18-2
- Condition: forecaster benchmark, Prophet vs seasonal naive (offline; no AWS)
- Traffic pattern: seasonal
- Data source: `seasonal_train_run1` (laptop, 2026-10-06-1) and
  `seasonal_c2dry_ec2_run1` (EC2, 2026-10-16-2)
- Duration / sample size: identical walk-forward windows for both models (W = 60,
  H = 10, S = 1): 200 paired forecasts (laptop), 250 (EC2)
- Configuration: seasonal naive = value one 30-minute cycle earlier
  (`src/forecasting/seasonal_naive.py`); its band = 2.5th/97.5th percentiles of
  the window's seasonal differences
- Results:

  | Data | Model | MAE (inv/min) | MAPE | Coverage | Band width |
  |---|---|---|---|---|---|
  | Laptop | Prophet | 250.2 | 1.89% | 94.5% | 1,730 |
  | Laptop | Seasonal naive | 320.3 | 2.50% | 97.5% | 2,244 |
  | EC2 | Prophet | 22.7 | 0.27% | 90.0% | 86 |
  | EC2 | Seasonal naive | 7.3 | 0.09% | 84.0% | 28 |

  - Laptop: Prophet has 22% less error, closer in 61% of forecasts.
  - EC2: seasonal naive has 3.1x less error; Prophet closer in only 18%.
- Notes / anomalies:
  - On noisy traffic (laptop, varying network) Prophet's smooth seasonal fit
    averages out noise that a copy of the last cycle repeats. On EC2 traffic,
    which repeats almost exactly (fixed requests per user, no noise), copying
    the last cycle is near-perfect and Prophet's 3-term Fourier fit carries a
    small systematic error.
  - The gap does not change any capacity decision: 15.4 invocations/min is
    0.26 req/s, about 0.01 environments with the EC2 fit. Forecast accuracy is
    not the limiting factor; the capacity conversion and headroom are.
  - Prophet's value therefore has to come from what seasonal naive lacks:
    calibrated bands (Layer 2), trend and drift handling, regressors and
    retraining (Layers 1 and 4). Recorded as Known issue 11.
  - Outputs: `results/rolling_forecast/<name>_snaive_*`, `<name>_comparison.csv`,
    `_comparison_by_horizon.csv`, `_comparison.png`.
- Figures:

  ![Prophet vs seasonal naive, laptop data](../results/rolling_forecast/seasonal_train_run1_comparison.png)
  ![Prophet vs seasonal naive, EC2 data](../results/rolling_forecast/seasonal_c2dry_ec2_run1_comparison.png)

  *Mean absolute error by forecast horizon for Prophet (blue) and seasonal
  naive (grey) on the same walk-forward origins: laptop data (top), EC2 data
  (bottom). Lower is better.*
  - How to read it: seasonal naive is the "copy the last cycle" baseline that
    any forecaster has to beat to be worth using.
  - What it shows: on noisy laptop traffic Prophet is lower at every horizon.
    On noise-free EC2 traffic the baseline is about 3x better (note the y axis
    is only 0-28 there), because a repeating sine is copied exactly.
- Next step: decide how to make the seasonal traffic realistic (seeded noise and
  drift, or a real trace) before the reported runs.

### Run: 2026-10-18-3
- Condition: traffic-realism check, Prophet vs seasonal naive on simulated
  traffic (offline: `TrafficPatternShape.users_at` evaluated directly, no Locust
  or AWS)
- Traffic pattern: seasonal, 95 min, `SEED=42`, 10 req/s per user
- Data source: simulated per-minute invocations (mean users x 600), first and
  last minute dropped
- Configuration: new `traffic_realism` config section: `noise_pct: 10`
  (per-minute multiplicative noise, capped at 3 sigma), `noise_interval_s: 60`,
  `drift_pct: 20` (linear rise in the base level over the run); separate RNG
  stream for noise
- Results:

  | Traffic | Users | Prophet MAE | Seasonal naive MAE | Skill | Coverage (P / SN) |
  |---|---|---|---|---|---|
  | Noiseless | 8-32 | 35 | 0 | n/a (naive exact) | 91% / 100% |
  | Realism on | 8-41 | 1,048 | 1,345 | +0.22 | 92% / 92% |
- Notes / anomalies:
  - Checks passed: realism off reproduces the old seasonal shape exactly; spike
    schedule identical with noise on; same seed gives identical traffic.
  - Noiseless simulated traffic repeats exactly, so seasonal naive has zero
    error, matching the EC2 finding (2026-10-18-2).
  - With realism on, peak load is about 410 req/s (41 users); EC2 has only been
    validated at 200 req/s, so watch throughput against design in the next run.
- Next step: second seasonal dry run on EC2 with realism on; it doubles as the
  out-of-sample test of the EC2 capacity calibration.

### Run: 2026-10-18-4 (ABORTED: stale code)
- Condition: vanilla-prophet, live dry run (intended as the out-of-sample run)
- Traffic pattern: seasonal, 95 min planned
- Data source: EC2 load generator, run `20261018-0742_seasonal_c2_dryrun`
- Duration / sample size: about 5 min (07:42-07:47 UTC), 75,619 requests, 0
  failures; stopped with the instance
- Results: none used
- Notes / anomalies:
  - `git pull` on the instance failed (two untracked controller CSVs from
    2026-10-16-2 would have been overwritten), so the run used commit `879a6cd`:
    no traffic realism, no `--history-start` fix, laptop calibration. Spotted from
    the commit in the start banner. Known issue 13; `run_experiment.sh` now
    refuses to start unless HEAD equals `origin/main`.
  - Its traffic ended about 2.6 min before 2026-10-18-5 started, which left
    that run's environments warm (Known issue 12).
- Next step: move the CSVs aside, pull, rerun (2026-10-18-5).

### Run: 2026-10-18-5
- Condition: vanilla-prophet, live dry run (decisions computed, Provisioned
  Concurrency never changed); out-of-sample test of the EC2 capacity calibration
  and first live run with traffic realism
- Traffic pattern: seasonal (`TrafficPatternShape`, `SEED=42`, `USER_RPS=10`,
  `NOISE_PCT=10`, `NOISE_INTERVAL_S=60`, `DRIFT_PCT=20`; 8-40 users)
- Data source: EC2 load generator (c7i-flex.large, commit `d71b1e0`), run
  `20261018-0750_seasonal_c2_dryrun`; CloudWatch export
  `data/raw/seasonal_c2dry_ec2_run2.csv`, trimmed to 07:51-09:24 in
  `data/processed/`
- Duration / sample size: 95 min, 07:50:02-09:25 UTC, 1,270,623 requests, 0
  failures; 95 controller ticks (64 warming up, 31 decisions, 29 scorable)
- Results:
  - P95 latency: 45 ms (P50 27, P99.9 65, max 3,125 ms)
  - P99 latency: 48 ms
  - Cold start count: 57 inits, all mid-run; 8 user-visible (> 1 s), at 1,803,
    1,984, 2,403 and 3,606 s; 47 returned in under 100 ms. No start-up cold
    starts because the aborted run had warmed the function (Known issue 12)
  - Cost per request: not computed (billed mean 5.9 ms)
  - Load accuracy: 98.4-100.2% of users x 10 req/s per minute (mean 100.0%),
    including 11 minutes at 35-40 users (about 400 req/s); P95 45 ms at every
    load level
  - CloudWatch vs Locust: 1,270,678 vs 1,270,623 invocations (+55)
  - Forecasters, walk-forward (W = 60, H = 10, S = 1, 250 paired forecasts):

    | Model | MAE (inv/min) | MAPE | Coverage | Band width |
    |---|---|---|---|---|
    | Prophet | 1,005.0 | 7.99% | 92.4% | 4,465 |
    | Seasonal naive | 1,266.5 | 9.46% | 92.0% | 5,199 |

    Skill +0.21, Prophet closer in 61% of forecasts (simulation predicted +0.22).
  - Live decisions (target vs actual peak concurrency in each decision's
    window): 7 of 29 under-provisioned (shortfalls 9, 8, 6, 5, 1, 1, 1), 1 exact,
    mean excess 2.07 environments; peak-forecast MAPE 11.3% (worst 33.3%)
  - Calibration out of sample (run-1 fit applied to all 94 minutes): residual
    mean +1.51, 26.6% of minutes above the headroom (designed for 5%), R^2 0.76;
    even a perfect forecast would leave 16 of 94 minutes under-provisioned
- Notes / anomalies:
  - First decision at 08:54, minute 64: the `--history-start` fix works live
    (Known issue 10).
  - The calibration error depends on load. Mean residual by request rate:
    <= 150 req/s +0.14, 150-250 +0.54, 250-320 +2.34, > 320 +3.92 (max 10.3).
    Run 1 only reached 320 req/s, so the fit is extrapolated at the new peaks,
    and concurrency rises faster than linearly there. Billed duration also rose
    (5.1 -> 5.9 ms mean). A refit on this run gives -0.48 + 0.0587 x req/s,
    headroom 3.82 (R^2 0.88). Known issue 7 stays open.
  - The worst shortfalls (9, 8, 6) are at the 08:54-09:02 peak, above 320
    req/s. The largest forecast errors (29-33%, 09:12-09:19) are over-forecasts
    on a noise dip, so they cost money but not cold starts.
  - Outputs: `results/rolling_forecast/seasonal_c2dry_ec2_run2_*` (Prophet,
    seasonal naive, comparison), `results/controller/20261018-0750_*.csv`
    (decision log, plus `_evaluation.csv` and `.png` from `evaluate_decisions.py`).
- Figures:

  ![Walk-forward Prophet forecast, EC2 seasonal run 2 with realism](../results/rolling_forecast/seasonal_c2dry_ec2_run2_forecast.png)

  *Same layout as Run 2026-10-10-1, on this run (noise 10%, drift 20%).*
  - What it shows: the traffic is now irregular minute to minute and each peak
    is higher than the last (drift). Prophet follows the cycle but cannot
    predict the random minute-to-minute noise, so error is about 8%. The
    actual line stays inside the band (92% coverage).

  ![Prophet vs seasonal naive, EC2 run 2](../results/rolling_forecast/seasonal_c2dry_ec2_run2_comparison.png)

  *Mean absolute error by horizon, Prophet vs seasonal naive.*
  - What it shows: with realistic traffic Prophet is better at every horizon
    (21% less error overall). This reverses the EC2 run 1 result and matches
    the simulation (Run 2026-10-18-3).

  ![Calibration out of sample and live decisions, EC2 run 2](../results/controller/20261018-0750_seasonal_c2_dryrun_evaluation.png)

  *(a) The run-1 calibration (line and dashed headroom) applied to this run
  (blue) and to the run it was fitted on (grey); dotted line = highest load in
  the calibration run. (b) The controller's target for each minute against the
  peak concurrency that arrived; orange dots = under-provisioned minutes.
  Produced by `src/evaluation/evaluate_decisions.py`.*
  - How to read it: in (a), blue points above the dashed line are minutes the
    rule would have under-provisioned even with a perfect forecast.
  - What it shows: below about 250 req/s the blue points fall on the grey ones,
    so the calibration transfers. Beyond the fitted range (right of the dotted
    line) they rise well above it. In (b) most shortfalls are at the 08:56-09:00
    peak (above 320 req/s) and at a single burst at 09:04. The target tracks
    the shape well; the error comes from the conversion rule, not the forecast.
- Next step: decide how to calibrate across the full load range (pool runs 1
  and 2 and test on a third, or add a non-linear term), fix the start protocol
  (Known issue 12), then the first `--apply` run.

### Run: 2026-10-29-1
- Condition: capacity-model comparison (offline; no AWS calls)
- Traffic pattern: seasonal
- Data source: `data/processed/seasonal_c2dry_ec2_run1.csv` (2026-10-16-2, 80-320 req/s)
  and `seasonal_c2dry_ec2_run2.csv` (2026-10-18-5, 80-400 req/s), 94 minutes each
- Configuration: `src/evaluation/compare_capacity_models.py`; linear fit of peak
  concurrency on request rate, margin at the 95th percentile, scored with a perfect
  forecast (each minute's actual rate) so only the capacity model is judged
  - additive: fit + residual quantile (the model used so far)
  - multiplicative: fit x quantile of actual / fitted (new `capacity.headroom_mode`)
  - leave-one-run-out (fit on one run, test on the other) and pooled (in-sample)
- Results:

  | Margin | Split | Under-provisioned minutes | Worst shortfall | Excess env-minutes (% of actual) |
  |---|---|---|---|---|
  | Additive | held out run 1 | 0 / 94 (0%) | 0 | 528 (55.0%) |
  | Additive | held out run 2 | 16 / 94 (17.0%) | 8 | 156 (13.2%) |
  | Additive | pooled | 9 / 188 (4.8%) | 5 | 684 (31.9%) |
  | Multiplicative | held out run 1 | 0 / 94 (0%) | 0 | 444 (46.2%) |
  | Multiplicative | held out run 2 | 17 / 94 (18.1%) | 8 | 122 (10.3%) |
  | Multiplicative | pooled | 4 / 188 (2.1%) | 5 | 662 (30.9%) |

  - Chosen: pooled multiplicative, concurrency = 0.17 + 0.0529 x req/s, x 1.26
    (R^2 0.858, 80-400 req/s); `controller.calibration_file` now points at
    `results/capacity_calibration/ec2_pooled_run1_run2.json`
  - Controller replay on run 2 (Prophet `yhat`, C2): under-provisioned decisions
    10/28 with the run-1 calibration -> 5/28 with the pooled one; mean excess
    1.2 -> 2.5 environments. On run 1: 0/28, mean excess 3.7. Both in-sample for
    the pooled fit.
- Notes / anomalies:
  - The two runs agree below about 250 req/s (mean concurrency per 50 req/s band
    within 0.5). At 250-350 req/s run 2 needs about 3 more environments than run 1
    at the same rate.
  - Request rate explains about 86% of concurrency. Billed duration adds nothing
    (correlation with the residual 0.01); the minute-to-minute change in rate adds a
    little (R^2 0.859 -> 0.868; run 2 changes about 34 req/s per minute vs 13 in
    run 1, from the 10% noise). Effective occupancy is about 52-57 ms per request
    (concurrency / rate), against about 5 ms billed.
  - The scatter grows with load (residual standard deviation 0.67 below 150 req/s,
    3.09 above 320), which is why a margin proportional to the fit suits it better
    than a constant one: fewer under-provisioned minutes pooled (2.1% vs 4.8%) and
    less spare capacity in every split.
  - Extrapolation is not fixed by either margin, nor by a quadratic fit (tested:
    17/94 when fitted on run 1 and tested on run 2, because run 1 has no curvature
    to learn). Rule adopted: the calibration data must cover the load range of the
    experiment it is used for. Seasonal runs peak at about 400 req/s; the spiky
    pattern (about 1,000 req/s) will need its own calibration coverage.
  - Outputs: `results/capacity_calibration/ec2_pooled_run1_run2.json`,
    `_comparison.csv`, `_comparison.png`; replay logs
    `results/controller/replay_pooled_run{1,2}.csv`.
- Figure:

  ![Capacity margin comparison, EC2 runs 1 and 2](../results/capacity_calibration/ec2_pooled_run1_run2_comparison.png)

  *(a) Peak concurrency per minute against request rate for both EC2 runs, with the
  pooled fit plus an additive margin (dashed) and a multiplicative margin (solid).
  (b) Share of minutes under-provisioned, and (c) spare capacity as a share of
  actual environment-minutes, for each margin when one run is held out and when
  both are pooled, scored with a perfect forecast.*
  - How to read it: in (b) lower is fewer cold-start minutes; the dotted line is the
    5% the 95th-percentile margin is designed for. In (c) lower is cheaper.
  - What it shows: the multiplicative margin sits lower at low load and higher at
    high load, following the widening scatter. It is cheaper in every split and
    halves under-provisioning when pooled. Holding out run 2 fails for both
    margins (17-18%), because run 1 never reached run 2's peak: the fix is
    calibration data that covers the load range, not a different margin.
- Next step: fix the start protocol (Known issue 12); use the next seasonal run as
  the held-out test of this calibration; then the first `--apply` run.

### Run: 2026-10-29-2 (ABORTED: instance stopped mid-run)
- Condition: vanilla-prophet, live dry run (intended as the held-out test of the
  pooled calibration from 2026-10-29-1)
- Traffic pattern: seasonal, `SEED=7` (new noise, same load range), 95 min planned
- Data source: EC2 load generator, run `20261029-1544_seasonal_c2_dryrun`
- Duration / sample size: about 3.5 min (15:44-15:47:34 UTC), first minute 12,043
  requests and 0 errors; nothing uploaded
- Results: none
- Notes / anomalies:
  - `git pull` on the instance failed again (two untracked controller CSVs from
    2026-10-18 now tracked in the repo), so the run started on commit `d71b1e0`,
    which predates the stale-code check in `run_experiment.sh` (Known issue 13).
  - `loadgen/session.sh stop` was run from the laptop straight after the start,
    which stopped the instance and killed the run. `results` and `stop` are for
    after the run has finished.
- Next step: move the two CSVs aside on the instance, pull to `f6ce563`, rerun with
  `SEED=7`, and leave the instance running until the run uploads to S3.

### Run: 2026-10-29-3 (ABORTED: instance stopped mid-run)
- Condition: vanilla-prophet, live dry run (held-out test, second attempt)
- Traffic pattern: seasonal, `SEED=7`
- Data source: EC2 load generator, run `20261029-1553_seasonal_c2_dryrun`, commit
  `f6ce563` (pull succeeded after moving the two CSVs aside)
- Duration / sample size: about 3 min (15:53 UTC until the instance stopped);
  first minute 12,428 requests, 0 errors; nothing uploaded
- Results: none
- Notes / anomalies: `loadgen/session.sh stop` was again run straight after the
  start (interrupted with Ctrl-C, but the stop request had already been sent).
  The next attempt (`20261029-1558_seasonal_c2_dryrun`) was started after the
  instance came back up. Its start banner warned of uncommitted changes: the `mv`
  was repeated after the pull, which deleted two tracked output CSVs from the
  instance's working tree. Code and config were unchanged, so the run still
  matches `f6ce563`.

### Run: 2026-10-29-4 (ABORTED: stopped by hand)
- Condition: vanilla-prophet, live dry run (held-out test, third attempt)
- Traffic pattern: seasonal, `SEED=7`
- Data source: EC2 load generator, run `20261029-1558_seasonal_c2_dryrun`, commit `f6ce563`
- Duration / sample size: about 4 min (15:58-16:02 UTC); traffic normal (9,994-17,595
  invocations per minute in CloudWatch); nothing uploaded
- Results: none
- Notes / anomalies: stopped by hand after a misunderstanding about the run length
  (95 min is required: about 63 min of warm-up before the first decision, then about
  30 decisions). The instance stayed running.

### Run: 2026-10-29-5
- Condition: vanilla-prophet, live dry run (decisions computed, Provisioned
  Concurrency never changed); held-out test of the pooled multiplicative
  calibration from 2026-10-29-1
- Traffic pattern: seasonal (`TrafficPatternShape`, `SEED=7`, `USER_RPS=10`,
  `NOISE_PCT=10`, `DRIFT_PCT=20`): same shape and load range as runs 1-2, new noise
- Data source: EC2 load generator (c7i-flex.large, commit `f6ce563`), run
  `20261029-1604_seasonal_c2_dryrun`; CloudWatch export
  `data/raw/seasonal_c2dry_ec2_run3.csv`, trimmed to 16:05-17:38 UTC in `data/processed/`
- Duration / sample size: 95 min, 16:04:29-17:39 UTC, 1,275,906 requests, 0
  failures; 29 scored decisions (17:10-17:38)
- Results:
  - P95 latency: 45.1 ms (P50 26.2, P99.9 67.1, max 3,175 ms)
  - P99 latency: 47.5 ms
  - Cold start count: 65 inits, all mid-run; 18 user-visible (> 1 s); 40 returned
    in under 100 ms. No start-up cold starts: the aborted attempts minutes earlier
    (2026-10-29-2 to -4) had left the function warm (Known issue 12)
  - Cost per request: about $2.1e-7 (billed mean 6.5 ms, 128 MB)
  - Load range: 85-366 req/s, concurrency 5-37
  - Live decisions with the pooled calibration, against the old run-1 calibration
    applied to the same forecasts (`yhat_max` from the decision log):

    | Calibration | Under-provisioned decisions | Shortfalls | Mean excess | Env-minutes |
    |---|---|---|---|---|
    | Run 1, additive (old) | 6 / 29 | 1, 1, 2, 2, 4, 5 | 1.93 | 427 |
    | Pooled, multiplicative (new) | 0 / 29 | none | 3.86 | 498 (+17%) |

  - Perfect-forecast check over all 94 minutes: under-provisioned 16/94 (17.0%) with
    the new calibration, 37/94 (39.4%) with the old; excess 11.5% vs 6.6% of
    actual env-minutes. Residual mean +2.63; 26.6% of minutes above the margin
    (designed for 5%)
- Notes / anomalies:
  - Concurrency per request rate rose again from session to session. Mean peak
    concurrency per load band (runs 1 / 2 / 3): up to 150 req/s 5.9 / 6.3 / 7.0;
    150-250 10.5 / 10.9 / 12.3; 250-320 14.0 / 16.1 / 19.2; above 320 n/a / 20.6 / 24.3.
    A calibration fitted on earlier sessions therefore drifts.
  - The outlier minutes coincide with bursts of cold starts: 16:35 (27
    environments, 15 cold starts), 16:40 (30, 3), 16:46 (34, 3), 17:06 (27, 9),
    17:08 (37, 1). A cold start holds an environment for about 3 s instead of about
    50 ms, so requests arriving meanwhile need further new environments: the
    concurrency spike is partly caused by the cold starts themselves. Under
    Provisioned Concurrency these minutes should be smaller, so a calibration
    measured under reactive scaling is conservative at those minutes.
  - The 0/29 result is real but favoured by timing: decisions start after the
    63-minute warm-up, and four of the five outlier minutes fell before 17:10.
  - Figure: `results/controller/20261029-1604_seasonal_c2_dryrun_evaluation.png`.
- Next step: discuss online recalibration (refit the capacity line every minute on
  the same 60-minute window Prophet uses, so session drift is absorbed); fix the
  start protocol (Known issue 12); then the first `--apply` run.

### Run: 2026-10-30-1
- Condition: reactive baseline (C1), traffic only; validation of the start protocol
  (Known issue 12), not one of the nine scenarios
- Traffic pattern: steady (`TrafficPatternShape`, `SEED=42`, `USER_RPS=10`,
  `NOISE_PCT=10`, `DRIFT_PCT=20`)
- Data source: EC2 load generator (c7i-flex.large, commit `349c334`), run
  `20261030-1756_steady_c1_traffic`; alias `prod` moved to freshly published
  version 12 before the run (`lambda_version: "12"`, `start_state: "fresh version
  (cold)"` in the meta file)
- Duration / sample size: 5 min, 17:56:34-18:01:31 UTC, 65,668 requests (about 221
  req/s), 0 failures
- Results:
  - P95 latency: 45.1 ms (P50 26.7, P99.9 72.8, max 3,621 ms)
  - P99 latency: 47.5 ms
  - Cold start count: 23, all within the first 10 s of the run, none afterwards;
    each 3.3-3.6 s (the simulated 3 s init)
  - Cost per request: about $2.2e-7 (billed mean 8.1 ms, 128 MB)
- Notes / anomalies:
  - The start protocol works: every run now starts from no warm environments,
    regardless of earlier traffic (compare 0 start-up cold starts in 2026-10-18-5
    and 2026-10-29-5).
  - Four earlier attempts (versions 8-11) failed in the `published-version-active`
    waiter with AccessDenied on `lambda:GetFunctionConfiguration` for the
    version-qualified ARN: the IAM statement first listed only the function and
    `:prod`. Fixed by allowing `function:sandbox-lambda:*` (commit `349c334`); the
    last failure came about 30 s after the apply, before IAM had propagated.
    Versions 8-11 were published but never received traffic.
  - The instance's `git pull` was again blocked by an untracked controller CSV that
    had since been committed from the laptop (moved to `~/stash`).
- Next step: online recalibration of the capacity model, then the first `--apply` run.

### Run: 2026-11-01-1
- Condition: vanilla-prophet (C2), live **apply**: first run in which the controller
  set Provisioned Concurrency; pipeline validation, not one of the nine scenarios
- Traffic pattern: seasonal (`TrafficPatternShape`, `SEED=7`, `USER_RPS=10`,
  `NOISE_PCT=10`, `DRIFT_PCT=20`): identical to the dry run 2026-10-29-5 (requests per
  minute correlate 1.000, ratio 0.999), so the two runs differ only in PC being set
- Data source: EC2 load generator (c7i-flex.large, commit `7e439d5`), run
  `20261101-1201_seasonal_c2_apply`; fresh version 14 (start protocol), handler now
  logs `init_type`; calibration `ec2_pooled_run1_run2.json`
- Duration / sample size: 95 min, 12:02-13:37 UTC, 1,275,412 requests, 0 failures;
  32 decisions (13:05-13:36), PC in charge from 13:07 (run minute 65)
- Results (apply vs the same-traffic dry run, run minutes 65-95, while PC was set):

  | | Dry run (no PC) | Apply (PC) |
  |---|---|---|
  | P95 / P99 latency | 44.9 / 47.0 ms | 45.8 / 49.0 ms |
  | Max latency | 250 ms | 2,085 ms |
  | User-visible cold starts (> 1 s) | 0 | 2 (minute 92) |
  | On-demand inits | 16 | 8 |
  | Billed duration mean | 6.58 ms | 6.03 ms |

  - Warm-up (minutes 0-63, no PC in either run): P99 47.7 vs 49.2 ms, visible cold
    starts 18 vs 24, so differences of 1-2 ms in P99 are between-session noise.
  - Whole run: 102 cold flags in the apply run, of which 29 were
    `provisioned-concurrency` (first request on a pre-warmed environment, no wait) and
    73 on-demand; 26 visible (20 at start-up).
  - PC configured: mean 17.9 environments, 574 env-minutes; about $0.018 at the
    us-east-1 list price ($0.0000041667 per GB-s, ap-south-1 price to confirm), about
    +21% on the on-demand cost of the same 31 minutes. The config was deleted at the
    end; none left allocated.
- Notes / anomalies:
  - Apply mode works end to end: first `put` at 13:05 (target 25), READY by 13:07,
    then one update per minute as the forecast changed, deleted on exit.
  - **Scale-up stalled (Known issue 14).** CloudWatch `ProvisionedConcurrencyUtilization`
    and `ProvisionedConcurrentExecutions` show usable PC following the targets down
    (25 -> 8, 13:11-13:22) but not back up: from 13:24 to 13:35 it stayed at about 9
    (utilisation 1.00 at 9 executions) while the API reported 10 -> 22 allocated.
    Every minute brought a new, larger target, so the config never left
    IN_PROGRESS. The one minute without a new target (13:35) was followed by usable PC
    rising to 14. Spillover to on-demand reached 70% of invocations at 13:33-13:34,
    the same minutes as the 2 visible cold starts.
  - The dry run had no visible cold starts in minutes 65-95 at all: on this
    sandbox, reactive scaling with proactive initialisation already copes with the
    one ramp inside the decision window. A 95-minute run (63 of them warm-up) gives
    too few ramps to measure a difference between conditions.
- Next step: fix the scale-up policy (Known issue 14); lengthen runs so the decision
  period covers several cycles (e.g. 155 min = 63 warm-up + 3 x 30-min cycles);
  then repeat this apply run with the same seed.

### Run: 2026-11-01-2
- Condition: vanilla-prophet (C2), offline replay (`--replay`, no AWS calls) of the
  scale-up policy fix for Known issue 14
- Traffic pattern: seasonal; CloudWatch exports of EC2 runs 1, 2 and 3
  (`data/processed/seasonal_c2dry_ec2_run{1,2,3}.csv`); run 3 has the same traffic as
  the apply run 2026-11-01-1 and was not used for calibration
- Method: `SimulatedPC` stands in for the PC API: a raise is usable `pc_ready_minutes`
  (2) after it is set, a put while a raise is IN_PROGRESS restarts it (as observed in
  2026-11-01-1), a lower is usable at once. Each minute after the first decision, the
  usable PC is compared with the measured peak concurrency.
- Results (29 scored minutes per run):

  | Run | every_minute (old): minutes short / shortfall | wait_for_ready (new): minutes short / shortfall | Configured env-min old -> new |
  |---|---|---|---|
  | 1 | 9 / 35 env-min | 0 / 0 | 415 -> 439 (+6%) |
  | 2 | 11 / 57 | 3 / 13 | 484 -> 512 (+6%) |
  | 3 (held-out) | 10 / 37 | 2 / 3 | 497 -> 523 (+5%) |

- Notes / anomalies:
  - The simulator reproduces the stall seen live: under every_minute, usable PC stays
    at 8 from 17:25 to 17:37 in run 3 while the target climbs to 25 (live: about 9).
    Under wait_for_ready it climbs 8 -> 10 -> 13 -> 17 -> 21 -> 25, alternating raise
    and held.
  - The scale-up window [now + 2, now + 5] needs a 9-step forecast, inside
    `lead_time_minutes: 10`.
  - The replay scores capacity against concurrency measured under reactive scaling,
    and the restart behaviour rests on one live observation; the live apply run is the
    real test.
  - Default run length raised to 155 min (63 warm-up + 3 x 30-min cycles of decisions).
- Next step: live apply run, `SEED=7`, 155 min, to confirm usable PC follows the
  configured value on the ramps and to count user-visible cold starts.

### Run: 2026-11-02-1
- Condition: vanilla-prophet (C2), live apply with `scale_up_policy: wait_for_ready`;
  validation of the Known issue 14 fix, not one of the nine scenarios
- Traffic pattern: seasonal (`SEED=7`, `USER_RPS=10`, `NOISE_PCT=10`, `DRIFT_PCT=20`);
  155 min, so the drift is spread over 155 min (not minute-identical to 2026-11-01-1)
- Data source: EC2 load generator (c7i-flex.large, commit `b6ce585`), run
  `20261102-1539_seasonal_c2_apply`; fresh version 15; calibration
  `ec2_pooled_run1_run2.json`
- Duration / sample size: 155 min, 15:39:35-18:14 UTC, 2,073,629 requests, 0
  failures; 92 decisions (16:43-18:14): 19 raise, 22 held, 37 lower, 14 keep
- Results:

  | Period | P95 / P99 (ms) | Max (ms) | Visible cold starts (> 1 s) | On-demand inits | Billed mean (ms) |
  |---|---|---|---|---|---|
  | Warm-up, minutes 0-63 (no PC) | 45.5 / 48.4 | 3,403 | 33 (20 at start-up) | 56 | 6.51 |
  | PC in charge, minutes 65-155 | 45.0 / 47.8 | 3,110 | 8 | 24 | 5.55 |
  | cycle 65-95 | 45.2 / 47.9 | 305 | 0 | 3 | 5.89 |
  | cycle 95-125 | 45.1 / 47.9 | 3,110 | 6 | 11 | 5.39 |
  | cycle 125-155 | 44.8 / 47.6 | 2,846 | 2 | 10 | 5.40 |

  - Cold flags: 85 on-demand, 58 `provisioned-concurrency` (no wait, excluded).
  - PC configured: mean 17.3 environments, 1,595 env-minutes, about $0.050 at the
    us-east-1 list price, +19% on the on-demand cost of the same period. Deleted at
    the end; none left allocated.
- Notes / anomalies:
  - **Stall fixed.** Usable PC (CloudWatch `ProvisionedConcurrentExecutions` /
    `ProvisionedConcurrencyUtilization`) followed the configured value on all three
    ramps, e.g. 10 -> 20 -> 22 (17:06-17:13), 9 -> 12 -> 17 -> 22 -> 24 -> 25
    (17:32-17:45), 12 -> 21 -> 25 -> 27 (18:07-18:14).
  - Mid-run visible cold starts fell from 13 in the two warm-up cycles (minutes 0-63,
    no PC) to 8 in the three PC cycles. This is not a controlled comparison (the
    warm-up cycles are earlier and lower in the drift); a C1 run of the same length
    and seed is needed.
  - Where the 8 came from: 5 at 17:14-17:15, the peak, where concurrency reached
    29-32 against 23 configured (the forecast and capacity model under-shot the
    peak; the max cap of 40 was not reached); 1 at 18:06 on a ramp where a raise
    took 5 min (Known issue 16); 2 at 17:41 and 18:12 with spare PC (Known issue 17).
  - Raise-to-READY times: 1 min (5 raises, all +1 or +2), 2 min (6), 3 min (6),
    5 min (2: 9 -> 10 at 17:01 and 10 -> 12 at 18:02, both right after another change).
- Next step: freeze the C2 controller and run C1 seasonal, `SEED=7`, 155 min, for the
  first like-for-like C1 vs C2 comparison.

### Run: 2026-11-03-1
- Condition: reactive baseline (C1), traffic only; like-for-like partner of the C2
  apply run 2026-11-02-1 (same seed, length, code and start protocol)
- Traffic pattern: seasonal (`SEED=7`, `USER_RPS=10`, `NOISE_PCT=10`, `DRIFT_PCT=20`),
  155 min; requests per minute correlate 1.0000 with 2026-11-02-1 (ratio 1.001)
- Data source: EC2 load generator (c7i-flex.large, commit `870fcfd`: same code as
  `b6ce585`, log changes only), run `20261103-0647_seasonal_c1_traffic`; fresh version 16
- Duration / sample size: 155 min, 06:47:33-09:22 UTC, 2,073,487 requests, 0 failures
- Results (C1 this run vs C2 2026-11-02-1):

  | Period | Condition | P95 / P99 (ms) | P99.9 (ms) | Visible cold starts (> 1 s) | On-demand inits | Billed mean (ms) |
  |---|---|---|---|---|---|---|
  | Warm-up 0-63 (no PC in either) | C1 | 46.2 / 50.4 | 76.2 | 23 (20 at start-up) | 58 | 6.81 |
  | | C2 | 45.5 / 48.4 | 70.4 | 33 (20 at start-up) | 56 | 6.51 |
  | Decisions 65-155 | C1 | 46.5 / 50.8 | 83.9 | 3 | 75 | 6.72 |
  | | C2 | 45.0 / 47.8 | 67.3 | 8 | 24 | 5.55 |

  - Cost per request, minutes 65-155 (us-east-1 list prices, ap-south-1 to confirm):
    C1 $2.14e-7, C2 $2.49e-7 (+16%), including PC allocation ($0.050) and the lower
    duration price for the 71% of invocations served by PC.
  - Per-minute P99 in minutes 65-155: C2 lower in 89 of 91 minutes (mean 47.4 vs 50.3 ms).
- Notes / anomalies:
  - Felt cold starts were **not** reduced: 3 (C1, all at minute 150) vs 8 (C2).
    Reactive Lambda with proactive initialisation already handles the gentle
    30-min seasonal ramps; most on-demand inits in C1 (75) were not felt.
  - The P99 gap is partly a session effect: C2 was already 2.0 ms lower in the
    warm-up, before any PC. Difference-in-differences (decision minus warm-up):
    C1 +0.4 ms, C2 -0.6 ms, so PC's own effect on P99 is about -1 ms.
  - Session-to-session spread in visible cold starts (3 vs 13 in identical warm-ups,
    Known issue 18) is larger than the difference between conditions.
  - Billed duration was 17% lower under C2 (5.55 vs 6.72 ms), consistent with the
    warm-up gap (6.51 vs 6.81) plus requests landing on pre-initialised environments.
- Interpretation: on predictable, gentle ramps, forecasting-based PC buys about 1 ms
  of P99 for +16% cost and does not reduce felt cold starts on this function.
  Proactive scaling can only pay off where reactive scaling has to create many
  environments quickly (sharp spikes).
- Next step: run the spiky row, where reactive scaling should struggle and C3's
  `yhat_upper` headroom matters most; plan replicates for the final comparison.

### Run: 2026-11-03-2
- Condition: reactive baseline (C1), traffic only; first spiky scenario run, also
  the calibration data source above 400 req/s
- Traffic pattern: spiky (`TrafficPatternShape`, `SEED=7`, `USER_RPS=10`,
  `NOISE_PCT=10`, `DRIFT_PCT=20`; base 20 users, x5 during 16 random spikes of
  63-117 s), 155 min
- Data source: EC2 load generator (c7i-flex.large, commit `f950ff3`, same code as the
  seasonal runs), run `20261103-1339_spiky_c1_traffic`; fresh version 17; CloudWatch
  export `data/processed/spiky_c1_ec2_run1.csv`
- Duration / sample size: 155 min, 13:39:35-16:14 UTC, 2,980,046 requests, 0 failures
- Results:
  - P95 / P99 latency: 110.7 / 186.5 ms overall; inside spikes 135.8 / 209.9 ms
    (P99.9 760.5); outside spikes 46.6 / 83.7 ms
  - Cold starts: 642 on-demand inits; **600 felt (> 1 s), 577 of them inside spikes**
    (20 at start-up, 3 elsewhere)
  - Felt cold starts per spike (start minute: count): 5.7: 56, 8.9: 0, 10.7: 0,
    18.9: 43, 22.1: 0, 27.7: 0, 47.2: 55, 49.5: 0, 65.0: 80, 82.0: 91, 88.3: 6,
    96.0: 58, 97.8: 0, 99.6: 18, 131.3: 88, 149.4: 82
  - Peak concurrency 130 (minute after a spike onset); above the PC cap of 40 in 36
    of 155 minutes; request rate 128-918 req/s per minute
- Notes / anomalies:
  - Spikes cost felt cold starts only when the previous spike was long enough ago
    for Lambda to reclaim its environments: every spike within about 6 min of the
    previous one had 0, every spike 10+ min after one had 43-91. This is the
    cold-start problem proactive capacity could remove.
  - **Load generator ceiling (Known issue 2):** in spikes Locust delivered 880 req/s
    against a 1,096 req/s mean target (80.4%), flat across spikes; outside spikes
    102%. Spike latency percentiles therefore include client-side queueing; the
    felt-cold-start count (3 s inits) is still valid.
  - Concurrency peaks of 100-130 coincide with cold-start bursts (each init holds an
    environment about 3 s); warm, 880 req/s needs about 47 environments by the pooled
    calibration (about 59 with the 1.26 margin).
  - The pooled calibration only covers 80-400 req/s; this run supplies 400-918.
- Next step: fix the generator ceiling (`--processes 2`) and rerun C1 spiky so the
  spiky row uses the full design load; raise `max_provisioned_concurrency` above 40
  before C2/C3 spiky; extend the calibration to the spiky load range.

### Run: 2026-11-04-1
- Condition: reactive baseline (C1), traffic only; rerun of 2026-11-03-2 with the
  load generator fix, and the C1 spiky result used in the 3x3 comparison
- Traffic pattern: spiky, identical to 2026-11-03-2 (`SEED=7`, `USER_RPS=10`,
  `NOISE_PCT=10`, `DRIFT_PCT=20`; same 16 spikes), 155 min
- Data source: EC2 load generator (c7i-flex.large, commit `a51d765`, Locust
  `--processes 2`), run `20261104-0439_spiky_c1_traffic`; fresh version 18;
  CloudWatch export `data/processed/spiky_c1_ec2_run2.csv`
- Duration / sample size: 155 min, 04:39:13-07:14 UTC, 3,217,025 requests, 0 failures
- Results:
  - Load delivered: inside spikes 1,045 req/s against a 1,096 target (**95.3%**, was
    80.4%), peak second 1,364; outside spikes 103.3%
  - P95 / P99 latency: 55.5 / 69.2 ms overall; inside spikes 60.3 / 80.0 ms
    (P99.9 478.2); outside spikes 46.2 / 55.7 ms
  - Cold starts: 630 on-demand inits; **566 felt (> 1 s), 545 of them inside spikes**
    (20 at start-up, 1 elsewhere)
  - Felt cold starts per spike (start minute, gap since previous spike ended: count):
    5.7 (start): 59, 8.9 (1.7): 0, 10.7 (0.3): 0, 18.9 (7.2): 33, 22.1 (1.9): 0,
    27.7 (4.5): 0, 47.2 (18.0): 68, 49.5 (0.5): 0, 65.0 (14.3): 76, 82.0 (15.2): 87,
    88.3 (4.9): 0, 96.0 (6.3): 62, 97.8 (overlap): 0, 99.6 (0.5): 0, 131.3 (30.7): 88,
    149.4 (16.7): 72
  - Concurrency (CloudWatch per-minute maximum): peak 128; above 70 in 27 of 154
    minutes, above 40 in 33; 174-1,194 req/s per minute
  - Cost (us-east-1 list prices, 128 MB, no PC): $0.694 total, $2.16e-7 per request
- Notes / anomalies:
  - The generator fix worked: spike load rose from 80.4% to 95.3% of target, and
    spike P99 fell from 209.9 ms to 80.0 ms, so most of the earlier spike latency was
    client-side queueing (Known issue 2). The remaining ~5% is mostly the ramp at
    each spike onset.
  - Felt cold starts barely changed (566 vs 600), and the same gap rule holds: every
    spike that started within 5 min of the previous one had 0, every spike 6.3+ min
    after one had 33-88. Two spikes that had a few felt cold starts last time (88.3,
    99.6) had 0 now; total spike count is consistent across the two sessions.
  - **The PC cap of 70 is too low for this load.** Even spikes with no cold starts
    (8.9, 10.7, 22.1, 27.7, 88.3) reached a per-minute maximum concurrency of 74-89,
    because a spike covers only part of a minute and its in-spike rate (~1,000-1,360
    req/s) is far above the per-minute average. The pooled calibration (80-400
    req/s) gives 72 x 1.26 = 91 at 1,364 req/s. Raise the cap to about 95 before
    C2/C3 spiky (~$0.18/h allocated at 95 x 128 MB).
  - Minutes with cold-start bursts (e.g. 64.8: 782 req/s, concurrency 128) inflate
    concurrency because each init holds an environment for ~3 s; exclude them when
    extending the calibration.
- Next step: extend the capacity calibration to the spiky range with warm minutes
  from runs 2026-11-03-2 and 2026-11-04-1; raise `max_provisioned_concurrency`; then
  C2 spiky (apply).

### Run: 2026-11-04-2
- Condition: analysis only (no AWS traffic); capacity calibration for the spiky row
- Data source: CloudWatch exports of C1 spiky runs 2026-11-03-2 and 2026-11-04-1
  (`data/processed/spiky_c1_ec2_run{1,2}.csv`) and their invoke logs
- Method:
  - `src/evaluation/warm_minutes.py` drops every minute in which any request that
    *started* in it was a felt cold start (> `evaluation.felt_cold_start_ms`, 1000 ms),
    writing `*_warm.csv`. Start time = log timestamp - response time: the log is
    stamped when the response arrives, so without this a burst starting at :57 landed
    in the next minute and its inflated minute stayed in (2026-11-03 15:50:
    242 req/s, concurrency 115). Dropped 14 of 155 and 9 of 154 minutes.
  - `src/evaluation/compare_capacity_models.py` on the two warm files,
    `--name ec2_spiky_run1_run2`; leave-one-run-out with a perfect forecast
- Results (multiplicative margin, the configured mode):
  - Pooled fit: concurrency = -1.91 + 0.0902 x req/s, x 1.44 (R^2 0.809, 128-1,194
    req/s). Seasonal pooled fit was 0.165 + 0.0529 x req/s, x 1.26
  - Held-out run 1: 3.5% of minutes under-provisioned (worst 23), 63.9% spare;
    held-out run 2: 3.4% (worst 45), 45.0% spare. Both within the 5% design target
  - Highest warm minute: concurrency 112 at 1,167 req/s (run 2); 78 in run 1, whose
    spikes were capped at 880 req/s by the load generator
- Notes / anomalies:
  - Spiky needs about 1.7x the environments per average req/s of seasonal. A 60-120 s
    spike fills only part of a minute, so the minute's peak concurrency reflects the
    in-spike rate while its invocation count reflects the average. Under-provisioned
    minutes are spike edges (a spike starting or ending a few seconds into a minute).
    This is a limit of minute-level forecasting, not of the fit.
  - Using a pattern-specific calibration matches how seasonal was done: each workload
    is calibrated on its own observed traffic before its C2/C3 runs, and C2 and C3
    share the same file, so the comparison between them is unaffected. The
    calibration traffic uses the same seed as the C2/C3 runs (also true for seasonal),
    so the fit is optimistic for unseen spiky traffic.
  - Config: `controller.calibration_file_by_pattern.spiky` points at the new file;
    seasonal keeps `ec2_pooled_run1_run2.json`. `max_provisioned_concurrency` 70 -> 120,
    just above the highest warm minute (112); 120 x 128 MB costs about $0.23/h
    while allocated. The controller prints which calibration and cap it loaded.
  - Replay check (C2, run 2 CloudWatch data) loaded the spiky file and cap 120 and ran
    without errors; its numbers are not a result (the replay sees the same run it
    was calibrated on).
- Next step: C2 spiky `--apply` run.

### Run: 2026-11-04-3
- Condition: vanilla Prophet (C2), `--apply`; first spiky run with Provisioned Concurrency
- Traffic pattern: spiky, identical to 2026-11-04-1 (`SEED=7`, `USER_RPS=10`,
  `NOISE_PCT=10`, `DRIFT_PCT=20`; same 16 spikes), 155 min
- Data source: EC2 load generator (c7i-flex.large, commit `dbf9550`, Locust
  `--processes 2`), run `20261104-0848_spiky_c2_apply`; fresh version 20; capacity model
  `ec2_spiky_run1_run2.json` (x 1.44), cap 120, `wait_for_ready`; CloudWatch export
  (with PC metrics) `data/processed/spiky_c2_apply_ec2_run1.csv`
- Aborted attempt first: `20261104-0843_spiky_c2_apply` (version 19) lost its controller
  window to a Ctrl-c about 2 min in; killed before any PC was set, files moved to
  `~/aborted` on the instance, not uploaded. Restarted 5 min later
- Instance stopped by a scheduled `autostop` tmux session at 11:45 UTC (deletes any PC,
  then `sudo shutdown -h now`); PC none afterwards
- Duration / sample size: 155 min, 08:48:18-11:23 UTC, 3,194,670 requests, 0 failures
- Results (C1 = run 2026-11-04-1, same traffic):
  - Felt cold starts (> 1 s): whole run 641 vs C1 566; **PC period (min 65-155) 407 vs
    386**; warm-up (no PC in either) 234 vs 180
  - Per spike in the PC period (C1/C2): 65.0: 76/66, 82.0: 87/111, 88.3: 0/0,
    96.0: 62/27, 97.8: 0/0, 99.6: 0/0, 131.3: 88/109, 149.4: 72/92
  - P95 / P99, PC period: 86.3 / 113.5 ms vs C1 54.9 / 68.2; inside spikes 102.5 / 131.7
    vs 60.5 / 79.1; outside spikes 46.4 / 66.1 vs 46.0 / 55.3. Warm-up (no PC):
    57.7 / 76.0 vs 56.3 / 71.0
  - PC: configured mean 39.8 (max 70), allocated mean 37.7 over the PC period, usable
    at most 50; 3,393 env-minutes; 73% of PC-period requests on provisioned
    environments, 468,946 spilled
  - Cost (us-east-1 list prices, 128 MB): whole run $0.787, **$2.46e-7 per request vs
    $2.16e-7 (+14%)**; PC period $2.69e-7 vs $2.16e-7 (+25%); PC allocation $0.106
- Notes / anomalies:
  - **C2 did not reduce cold starts under spiky traffic.** Spikes need 80-123
    concurrent environments; PC at spike onsets was 0-50. Vanilla Prophet forecasts
    the per-minute level, and random spikes are not in that level, so PC sized for
    the base load is fully used by it and every spike spills ~50-90 environments to
    on-demand, which start cold after a long gap exactly as in C1.
  - The forecast echoes past spikes: after the 96-100 min cluster, configured PC sat at
    48-59 for ~20 min while concurrency was 13-18 (10:30-10:48). PC is raised after
    spikes, not before them. This is what Layer 3 (residual anomaly override) and the
    wider `yhat_upper` band (Layer 2) are meant to address, so C3 spiky is the test.
  - Per-spike counts differ by up to ~35 between sessions under identical conditions
    (27.7 had 0 in C1 and 34 in C2, both before any PC; Known issue 18), so the PC-period
    difference (407 vs 386) is within session noise: no reduction, no clear increase.
  - In-spike latency got worse with PC: Known issue 19. Not CPU on the load generator:
    no second-of-minute pattern, outside-spike P95 unchanged, one controller step
    ~0.05 s of CPU.
- Next step: C3-layer2 spiky (`--apply`), same traffic; then Layer 3 in the live
  controller.

### Run: 2026-11-06-1
- Condition: enhanced Prophet, Layer 2 only (C3-layer2: scale to `yhat_upper`), `--apply`
- Traffic pattern: spiky, identical to 2026-11-04-1 and -3 (`SEED=7`, `USER_RPS=10`,
  `NOISE_PCT=10`, `DRIFT_PCT=20`; same 16 spikes), 155 min
- Data source: EC2 load generator (c7i-flex.large, commit `6ff6723`: code identical to
  the C2 run, the commit only adds its log entry; Locust `--processes 2`), run
  `20261106-0420_spiky_c3-layer2_apply`; fresh version 21; capacity model
  `ec2_spiky_run1_run2.json`, cap 120, `wait_for_ready`; CloudWatch export (with PC
  metrics) `data/processed/spiky_c3l2_apply_ec2_run1.csv`. Instance stopped by the
  scheduled `autostop` at 07:15 UTC; PC none afterwards
- Duration / sample size: 155 min, 04:20:55-06:56 UTC, 3,205,565 requests, 0 failures
- Results (C1 = 2026-11-04-1, C2 = 2026-11-04-3, same traffic):
  - Felt cold starts (> 1 s), PC period (min 65-155): **C1 386, C2 407, C3 144 (-63%
    vs C1)**; whole run 566 / 641 / 327; warm-up (no PC) 180 / 234 / 183
  - Per spike in the PC period (C1/C2/C3): 65.0: 76/66/0, 82.0: 87/111/56, 88.3: 0/0/0,
    96.0: 62/27/0, 97.8: 0/0/2, 99.6: 0/0/0, 131.3: 88/109/43, 149.4: 72/92/41
  - P95 / P99, PC period: C1 54.9 / 68.2, C2 86.3 / 113.5, C3 84.9 / 114.8 ms; inside
    spikes 60.5 / 79.1, 102.5 / 131.7, 101.0 / 130.5; outside spikes 46.0 / 55.3,
    46.4 / 66.1, 46.9 / 66.6
  - PC: configured mean 106.1 (cap 120 reached in 21 minutes), allocated mean 102.7,
    usable at most 97; PC at spike onsets 85-114 (C2: 0-50); 96% of PC-period requests
    on provisioned environments, 78,410 spilled (C2: 468,946)
  - Cost per request (us-east-1 list prices, 128 MB), whole run: C1 $2.16e-7, C2
    $2.46e-7, **C3 $3.02e-7 (+40% vs C1)**; PC period $2.16e-7 / $2.69e-7 / $3.67e-7
    (+70%); PC allocation $0.289 (C2 $0.106)
- Notes / anomalies:
  - First condition that reduced cold starts: the difference (386 -> 144) is far larger
    than the session-to-session spread per spike (up to ~35, Known issue 18). Two long-gap
    spikes went to 0 (65.0, 96.0); three were roughly halved (82.0, 131.3, 149.4).
  - How: under spiky traffic Prophet's band is very wide (the preliminary
    `yhat_upper` result), so scaling to `yhat_upper` keeps PC near 100 most of the
    time instead of chasing spikes. That is close to a static high PC level, and
    costs like one: +40% per request. An examiner may ask whether a static PC of ~100
    would do as well; that is not in the 3x3 design.
  - Remaining felt cold starts sit in spikes with spillover although allocated PC was
    at or above concurrency (82.0: 99 allocated, peak 85, 20,478 spilled), the
    spillover-with-free-PC behaviour of Known issue 17.
  - Tail latency did not improve: in-spike P95 is the same as C2 (~101 ms vs C1 60.5),
    for provisioned and on-demand environments alike (Known issue 19). The cold-start
    gain shows at P99.9 inside spikes (500.8 ms vs C2 591.8, C1 527.7) more than at
    P95/P99, because felt cold starts are under 0.1% of requests.
- Next step: Layer 3 (residual anomaly override) in the live controller and the full C3
  run; decide with the supervisor whether to add a static-PC diagnostic run (Known
  issue 19, and the static-PC question above); steady row.

### Run: 2026-11-06-2
- Condition: analysis and replay only (no AWS); Layer 3 (z-score residual override)
  design check and implementation
- Data source: CloudWatch exports `data/processed/spiky_c1_ec2_run2.csv` (C1 spiky,
  2026-11-04-1) and `data/processed/seasonal_c2dry_ec2_run2.csv`
- Method:
  - Detection timing: one-step-ahead Prophet forecast of each minute from the 60
    minutes before it (no leakage), residual = actual - yhat, rolling z-score over 30
    residuals, threshold 2.0 (`ZScoreAnomalyDetector` as written). A minute is visible
    to the controller 1 + `cloudwatch_delay_minutes` (3) after it starts, and a raise is
    usable `pc_ready_minutes` (2) later
  - Implementation replayed with `--condition c3-layer2` and `--condition c3-layer23`
    on both files
- Results:
  - Detection works: 7 of 8 spikes after warm-up flagged (z 2.3-21.7); all 11 flags were
    upward. The spike at 99.6 scored z 1.82 because earlier spike residuals stayed in
    the window and inflated the std
  - Timing does not: every override would be usable 5.8-6.8 min after its spike began,
    after the spike (60-120 s) had ended (e.g. spike 65.0-66.8 -> usable 70.8;
    131.3-132.6 -> 136.8)
  - Replay of the implementation, spiky: 11 flagged minutes, 11 overrides, all of them
    after the spike they answer; usable PC below concurrency 5/89 minutes for both
    `c3-layer2` and `c3-layer23` (shortfall 74 vs 77 env-min), configured env-min +0.2%.
    Seasonal: 0 flags, identical decisions
- Decision (with the student): implement Layer 3 as proposed, not as an
  anomaly-triggered hold, and report the detection lag as a measured limit:
  - Residual of the newest complete minute against a forecast from the window one
    minute earlier (`plan(residual=True)`), scored once per minute (`Layer3`)
  - z > +threshold: `target` and `target_up` raised to at least
    `capacity_model.target(observed invocations)`, the same calibrated conversion as the
    forecast (the old stub's fixed 10 requests per environment is not used). Lasts
    while that minute is flagged
  - z < -threshold: logged only, never lowers PC (cost asymmetry, as in the capacity
    margin)
  - Flagged residuals are kept out of the detector window (`exclude_anomalies`), so the
    spread describes normal error; `zscore_min_residuals: 10` before any flag
  - Config: `forecasting.zscore_window_minutes: 30`, `zscore_min_residuals: 10`;
    condition `c3-layer23` in `live_controller.py` and `run_experiment.sh`; decision log
    gains residual_ds, residual_y, residual_yhat, z_score, anomaly, override_target
- Notes / anomalies:
  - Scoring starts at minute 64 (needs 61 minutes of data) and flags from about
    minute 74, so the first spike after warm-up (65.0) can never be flagged.
  - Expected outcome of the live run: little or no cold-start change against
    `c3-layer2` on spiky traffic, because Layer 2 already holds PC near the cap and
    Layer 3 reacts ~6 min late. That is a result about reactive overrides on
    CloudWatch data, not a reason to change the design after seeing it.
- Next step: C3-layer23 spiky `--apply` run, same traffic.


### Run: 2026-11-06-3
- Condition: enhanced Prophet, Layers 2 + 3 (C3-layer23: scale to `yhat_upper`, z-score
  residual override), `--apply`
- Traffic pattern: spiky, identical to 2026-11-04-1, 2026-11-04-3 and 2026-11-06-1
  (`SEED=7`, `USER_RPS=10`, `NOISE_PCT=10`, `DRIFT_PCT=20`; same 16 spikes), 155 min
- Data source: EC2 load generator (c7i-flex.large, commit `ec2361f`, Locust
  `--processes 2`), run `20261106-0809_spiky_c3-layer23_apply`; fresh version 22;
  capacity model `ec2_spiky_run1_run2.json`, cap 120, `wait_for_ready`; Layer 3 window
  30, min residuals 10, threshold 2.0; CloudWatch export (with PC metrics)
  `data/processed/spiky_c3l23_apply_ec2_run1.csv`. Instance stopped by the scheduled
  `autostop` at 11:05 UTC; PC none afterwards
- Duration / sample size: 155 min, 08:09:38-10:45 UTC, 3,209,970 requests, 0 failures
- Results (C1 = 2026-11-04-1, C2 = 2026-11-04-3, L2 = C3-layer2 2026-11-06-1, L23 = this
  run; same traffic):
  - Felt cold starts (> 1 s), PC period (min 65-155): C1 386, C2 407, L2 144, **L23 143**;
    whole run 566 / 641 / 327 / 361; warm-up (no PC) 180 / 234 / 183 / 218
  - Per spike in the PC period (C1/C2/L2/L23): 65.0: 76/66/0/1, 82.0: 87/111/56/47,
    88.3: 0/0/0/0, 96.0: 62/27/0/18, 97.8: 0/0/2/0, 99.6: 0/0/0/0, 131.3: 88/109/43/42,
    149.4: 72/92/41/35
  - P95 / P99, PC period: L23 78.3 / 109.7 ms (L2 84.9 / 114.8, C1 54.9 / 68.2); inside
    spikes 94.9 / 124.7 (L2 101.0 / 130.5, C1 60.5 / 79.1); outside 47.4 / 68.4
  - PC: configured mean 105.5 (cap 120 reached in 24 minutes), allocated mean 101.7 (L2
    102.7), usable at most 90; PC at spike onsets 87-111 (L2 85-114); 95% of PC-period
    requests on provisioned environments, 87,514 spilled (L2 78,410)
  - Layer 3: 91 minutes scored, 10 flagged (all upward, z 2.2-16.3), 10 overrides. Each
    flag answers the minute a spike started (82.4, 88.4, 96.4-99.4, 131.4-132.4,
    149.4-150.4) and is decided 4 min after it (1 + `cloudwatch_delay_minutes`). Of the
    10 overrides, 7 were "held" (5) or "keep" (2) (PC already at or near the override target, or
    an allocation still IN_PROGRESS); 3 raised PC (at 92.4, 101.4, 153.4), each after the
    spike or cluster it answers had ended. No override was usable during a spike
  - Cost per request (us-east-1 list prices, 128 MB), whole run: C1 $2.16e-7, C2
    $2.46e-7, L2 $3.02e-7, **L23 $3.01e-7**; PC period $3.65e-7; PC allocation $0.286
- Notes / anomalies:
  - Layer 3 changed nothing measurable on spiky traffic: 143 vs 144 felt cold starts in
    the PC period, same cost, same PC levels. Per-spike differences (96.0: 0 vs 18) are
    within the session-to-session spread (Known issue 18). This matches the replay
    prediction of Run 2026-11-06-2, made before the run.
  - Reason, measured live: a flag needs the spike minute to be complete and published
    (1 + 3 min), then PC needs ~2 min to become usable, ~6 min in total, while spikes
    last 1-2 min. With Layer 2 PC already near the cap, an override also rarely has
    room to raise anything.
  - In-spike P95 is ~6 ms lower than L2 (94.9 vs 101.0) but still far above C1 (60.5);
    treat as noise until repeated (Known issue 19).
  - Warm-up cold starts (no PC, identical for every condition) ranged 180-234 across the
    four sessions, so session noise alone moves the whole-run total by ~50.
- Next step: Layer 1 (CloudWatch regressors) and Layer 4 (sliding-window retraining),
  then full C3; C3 seasonal; steady row; ask the supervisor about a static-PC diagnostic
  and repeat runs.

### Run: 2026-11-10-1
- Condition: replay only (no AWS); Layers 1 and 4 implemented, full C3 (`--condition c3`,
  Layers 1-4) and a layer-by-layer ablation (`--layers`)
- Data source: CloudWatch exports of C1 spiky runs 1 and 2
  (`data/processed/spiky_c1_ec2_run{1,2}.csv`) and seasonal C2 dry runs 1-3
  (`data/processed/seasonal_c2dry_ec2_run{1,2,3}.csv`, 94 min each, 29 scored minutes)
- Design decisions (with the student, before the replays):
  - Layer 1: Prophet needs a regressor's value for every forecast minute, and those
    minutes have no CloudWatch data yet, so a same-minute regressor would leak future
    data. `ConcurrentExecutions` enters lagged by `regressor_lag_minutes: 9`, equal to the
    decision's `steps_ahead` (all 92 decisions of Run 2026-11-06-3); `plan()` raises an
    error if the lag is shorter than steps_ahead. Values are looked up only in data the
    controller had seen. Duration is not used: it changes environments per request,
    which the capacity model already covers, not demand
  - Layer 4: every Prophet condition (C2 too) already refits each minute on a sliding
    60-min window, so "sliding-window retraining" alone would not separate C3 from C2.
    Layer 4 makes the window length adaptive: if |median of the newest 10 residuals -
    mean| > 1.0 x std of normal residuals (Layer 3's window, spikes excluded), the
    window restarts at the oldest of those 10 minutes (at least 30 min, one seasonal
    cycle) and grows back to 60 by one minute per minute. `retrain_window_hours: 24`
    (unused stub value) removed from the config
  - Condition `c3` = Layers 1-4; `--layers` (replay only) runs any subset on the same data
- Results (minutes with usable PC below measured concurrency / shortfall env-min /
  configured env-min):

  | Data | L23 | L123 | L234 | L1234 (full C3) |
  |---|---|---|---|---|
  | spiky run 1 | 4/90, 124, 8,289 | 4/90, 124, 8,327 | 5/90, 232, 7,683 | 5/90, 227, 7,658 |
  | spiky run 2 | 5/89, 77, 9,482 | 6/89, 89, 9,520 | 5/89, 172, 8,662 | 6/89, 179, 8,781 |
  | seasonal run 1 | 0/29, 0, 440 | same | same | same |
  | seasonal run 2 | 2/29, 7, 586 | - | - | 2/29, 7, 589 |
  | seasonal run 3 | 0/29, 0, 577 | 0/29, 0, 579 | 0/29, 0, 577 | 0/29, 0, 579 |

  - Regression check: `c3-layer23` replay on spiky run 2 reproduces Run 2026-11-06-2
    exactly (5/89, 77 env-min)
  - Layer 1: no measurable effect on either pattern (configured env-min within 0.5%)
  - Layer 4: 0 restarts on seasonal; 3-4 restarts per spiky run, 47-49 decisions on a
    shortened window. Restarts go both ways (drift scores +1.08 to +1.22 and -1.04 to
    -1.45), just above the 1.0 threshold
  - Layer 4 on spiky: usable PC falls to 32 (L23: 69-87 minimum), configured env-min
    -7 to -9%, shortfall roughly doubles (124 -> 232, 77 -> 172)
- Notes / anomalies:
  - Why Layer 4 hurts on spiky traffic: the spike process does not change, but after a
    spike cluster the forecast stays high (negative residuals) and before the next
    cluster it runs low, so the median test reads "drift". The restarted 30-min window
    holds fewer spikes, Prophet's band narrows, and `yhat_upper` falls. Layer 2's gain on
    spiky traffic partly comes from the window *remembering* past spikes (the "echo" of
    Run 2026-11-04-3); Layer 4 forgets them. Adaptive retraining and confidence-bound
    scaling pull against each other here.
  - The false-restart estimate (about once per 100 min) assumed roughly normal residuals;
    spiky residuals are not, so restarts came every ~25 min.
  - Neither pattern contains a real level shift (only 20% linear drift), which is what
    Layer 4 is for; it is never triggered where it could help. A level-shift pattern is
    outside the 3x3 design (limitation / future work).
  - Seasonal replays have only 29 scored minutes each, too few to separate layers.
  - Parameters kept as designed, not tuned on these replays (same principle as Layer 3).
- Next step: full C3 spiky `--apply` run (`SEED=7 loadgen/run_experiment.sh spiky c3 apply`).
  Expected from replay: fewer PC env-min and more felt cold starts than C3-layer23.
