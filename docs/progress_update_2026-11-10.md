# Progress update — up to 10 Nov 2026

(Working notes for the supervisor meeting. Every number is from docs/EXPERIMENT_LOG.md; run IDs in brackets.
All live runs: sandbox-lambda, ap-south-1, 128 MB, 155 min, EC2 load generator, `SEED=7`, fresh Lambda version per run.
Minutes 0-63 = warm-up with no PC in any condition (within-run control); minutes 65-155 = controller in charge ("PC period").)

## 1. 3×3 status

| | Steady | Spiky | Seasonal |
|---|---|---|---|
| C1 Reactive | not run | Done (2026-11-04-1) | Done (2026-11-03-1) |
| C2 Vanilla Prophet | not run | Done (2026-11-04-3) | Done (2026-11-02-1) |
| C3 Enhanced (Layers 1-4) | not run | Done (2026-11-10-2) + layer ablation | Running (started 10 Nov 14:01 UTC), results not in yet |

Ablation runs on spiky traffic (same traffic, live): Layer 2 only (2026-11-06-1), Layers 2+3 (2026-11-06-3).
5 of 9 cells done, 6th running.

## 2. Pipeline work that made the runs comparable (Oct – early Nov)

| Problem found | Fix | Evidence |
|---|---|---|
| Laptop load generator throttled (~45 req/s cap) | Locust + controller moved to EC2 c7i-flex.large in ap-south-1 | 2026-10-16-1 |
| Single Locust process capped spikes at 880 req/s (80.4% of target) | `--processes 2` | Spikes now 95.3% of target (peak 1,364 req/s); spike P99 209.9 → 80.0 ms (2026-11-04-1) |
| Runs started with environments already warm | Publish a fresh Lambda version per run | 23 start-up cold starts, all in first 10 s, none after (2026-10-30-1) |
| Controller could train on data from before the run | `--history-start` = run's first full minute | First decision at minute 64 (2026-10-18-5) |
| Re-targeting PC every minute restarts allocation (usable PC stuck at 9) | `scale_up_policy: wait_for_ready` | Usable PC follows configured on every ramp (2026-11-02-1) |
| Seasonal traffic was an exact sine; seasonal-naive beat Prophet 3× | Seeded noise (10%) + drift (20%) | Prophet skill over seasonal-naive +0.21 live (2026-10-18-5) |
| `cold_start` flag overcounts (PC envs + proactive init) | Primary metric = **felt cold start** (response > 1 s); on-demand inits reported alongside | Known issue 15 |

Measured PC allocation time: 84 s in the first test; in live runs raises took 1-5 min to READY (median 2).

## 3. All four enhancement layers are now implemented

- **Layer 1 – CloudWatch regressor:** ConcurrentExecutions, lagged by 9 minutes. Lag ≥ how far ahead each decision forecasts (9 min), so no future data leaks; the code refuses a shorter lag.
- **Layer 2 – Confidence-bound scaling:** scale to `yhat_upper` instead of `yhat`.
- **Layer 3 – Z-score residual override:** residual of the newest minute vs a forecast that had not seen it; z > 2 over the last 30 residuals → provision at least what that minute needed.
- **Layer 4 – Adaptive retraining window:** every Prophet condition (C2 too) already retrains each minute on a sliding 60-min window, so Layer 4 adapts the window *length*: if the forecast has been biased for most of the last 10 minutes, the window restarts at the change (min 30 min) and grows back to 60.

Each layer was replayed on recorded CloudWatch data before its live run; the live outcome matched the replay prediction each time (2026-11-06-2, 2026-11-10-1).

## 4. Spiky results (identical traffic in every run: 16 spikes, 63-117 s, ×5 load)

### 4.1 Headline, PC period (minutes 65-155)

| | C1 Reactive | C2 Vanilla | Layer 2 | Layers 2+3 | Full C3 (1-4) |
|---|---|---|---|---|---|
| Felt cold starts (> 1 s) | 386 | 407 | 144 | **143** | 196 |
| Change vs C1 | – | +5% | −63% | −63% | −49% |
| Warm-up control, min 0-63 (no PC) | 180 | 234 | 183 | 218 | 208 |
| P95 / P99, whole PC period (ms) | 54.9 / 68.2 | 86.3 / 113.5 | 84.9 / 114.8 | 78.3 / 109.7 | 90.7 / 119.0 |
| P95 / P99 inside spikes (ms) | 60.5 / 79.1 | 102.5 / 131.7 | 101.0 / 130.5 | 94.9 / 124.7 | 107.0 / 138.9 |
| P95 / P99 outside spikes (ms) | 46.0 / 55.3 | 46.4 / 66.1 | 46.9 / 66.6 | 47.4 / 68.4 | 46.3 / 70.9 |
| Average PC allocated | 0 | 37.7 | 102.7 | 101.7 | 92.1 |
| Requests served by PC | 0% | 73% | 96% | 95% | 93% |
| Requests spilled to on-demand | all | 468,946 | 78,410 | 87,514 | 119,455 |
| PC allocation cost | – | $0.106 | $0.289 | $0.286 | $0.259 |
| Cost per request (whole run) | $2.16e-7 | $2.46e-7 (+14%) | $3.02e-7 (+40%) | $3.01e-7 (+39%) | $2.93e-7 (+35%) |

(Cost at us-east-1 list prices, 128 MB; ap-south-1 prices still to confirm.)

### 4.2 Felt cold starts per spike, PC period

| Spike start (min) | C1 | C2 | L2 | L23 | Full C3 |
|---|---|---|---|---|---|
| 65.0 | 76 | 66 | 0 | 1 | 0 |
| 82.0 | 87 | 111 | 56 | 47 | 48 |
| 88.3 | 0 | 0 | 0 | 0 | 0 |
| 96.0 | 62 | 27 | 0 | 18 | 0 |
| 97.8 | 0 | 0 | 2 | 0 | 0 |
| 99.6 | 0 | 0 | 0 | 0 | 0 |
| **131.3** | 88 | 109 | 43 | 42 | **101** |
| 149.4 | 72 | 92 | 41 | 35 | 47 |

In C1, a spike causes cold starts only if it starts ≥ ~6 min after the previous one (Lambda has reclaimed its environments by then); spikes within ~5 min of the previous one had 0.

### 4.3 Key points

- **C2 (vanilla) does not reduce cold starts.** PC at spike onset was 0-50 against 80-123 environments needed: the point forecast follows the average, and random spikes are not in it. It also keeps PC at 48-59 for ~20 min after a spike cluster while concurrency was 13-18 (echo of past spikes).
- **Layer 2 is what works:** under spiky traffic Prophet's band is very wide, so `yhat_upper` keeps PC at 85-114 at spike onsets → cold starts −63%, at +40% cost per request. The gain (386 → 144) is far larger than the session-to-session spread (up to ~35 per spike).
- **Layer 3 detects spikes but too late:** flagged 10 spikes correctly, but every override arrives ~6 min after the spike began (1 min + 3 min CloudWatch delay + 2 min PC ready), while spikes last 1-2 min. No measurable change (143 vs 144). Predicted by replay before the live run.
- **Layer 4 conflicts with Layer 2:** 4 window restarts, 49 of 92 decisions on a shortened window. On spiky traffic it reads the bias before/after spike clusters as "drift", the shortened window forgets past spikes, the band narrows and PC drops. At the spike at minute 131 PC was 38 (vs 99 with Layers 2+3) → 101 vs 42 cold starts. That one spike explains the whole difference (+59 of +53 total). Also predicted by replay.
- **Layer 1:** no measurable effect in replay on either pattern (configured env-min within 0.5%); cannot be separated in the live run.
- **Tail latency does not improve with PC** (see 7.2). The cold-start gain shows at P99.9 inside spikes (L2 500.8 ms vs C2 591.8, C1 527.7), because felt cold starts are < 0.1% of requests.

## 5. Seasonal results so far (minutes 65-155)

| | C1 (2026-11-03-1) | C2 (2026-11-02-1) | C3 |
|---|---|---|---|
| Felt cold starts | 3 | 8 | running |
| Warm-up control (min 0-63) | 23 (20 at start-up) | 33 (20 at start-up) | |
| P95 / P99 (ms) | 46.5 / 50.8 | 45.0 / 47.8 | |
| P99.9 (ms) | 83.9 | 67.3 | |
| On-demand inits | 75 | 24 | |
| Average PC configured | 0 | 17.3 | |
| Cost per request | $2.14e-7 | $2.49e-7 (+16%) | |

- On gentle 30-min ramps, Lambda's reactive scaling already copes: forecasting buys ~1 ms P99 (difference-in-differences vs warm-up: C1 +0.4 ms, C2 −0.6 ms) for +16% cost, and does not reduce felt cold starts.
- C2's 8 felt cold starts: 5 at the peak (forecast + capacity model under-shot: concurrency 29-32 vs 23 configured), 1 on a slow (5 min) PC raise, 2 with spare PC (spillover).
- In replay, Layers 3 and 4 never fired on seasonal data, so C3 seasonal is expected to behave close to Layer 2 only.

## 6. Answers to the two earlier questions

- **How data is fed into Prophet:** every minute, train on the newest 60 complete minutes (data older than now − 3 min, because CloudWatch publishes late); forecast the minutes the decision is responsible for (now + 2 to now + 5, 9 steps past the newest data); step 1 minute. Nothing after the decision time enters training (enforced by `--history-start` and the lagged regressor). Layer 4 changes only the window length.
- **How thresholds are set:** forecast req/min → PC with a capacity model fitted on measured CloudWatch data (concurrency vs request rate, warm minutes only), plus a headroom margin = 95th percentile of the fit's residuals (multiplicative).
  - Seasonal: concurrency = 0.165 + 0.0529 × req/s, × 1.26
  - Spiky: concurrency = −1.91 + 0.0902 × req/s, × 1.44 (R² 0.809, 128-1,194 req/s); held-out runs 3.4-3.5% of minutes under-provisioned (within the 5% target). Spiky needs ~1.7× the environments per average req/s, because a 60-120 s spike fills only part of a minute.
  - Cap 120 = just above the highest warm minute measured (112).

## 7. Decisions and issues to discuss

1. **Reporting (Option B):** report full C3 as the C3 cell **and** the layer-by-layer results (Layer 2 / Layers 2+3 / all four). For seasonal and steady, layer subsets get a live run only if replay shows they make different decisions. — *Agree?*
2. **Latency inside spikes rises whenever PC is allocated** (~101 ms vs 60.5 ms in C1), for provisioned and on-demand environments alike; outside spikes and warm-up unchanged; billed duration unchanged (median 2 ms), so the extra time is outside the function. Suggest one diagnostic run with a fixed PC of ~100 to test if it is a PC side effect. — *Worth adding?*
3. **Single runs are noisy:** identical warm-ups (no PC) gave 180-234 felt cold starts across five spiky sessions. — *Repeat runs for the key cells, and how many?*
4. **Static-PC question:** Layer 2 on spiky behaves close to a fixed PC ≈ 100. An examiner may ask whether a fixed PC would do as well. (Same diagnostic run as point 2 would answer both.)
5. **Layer 4 result:** it is never triggered where it could help (neither pattern has a real level shift) and hurts on spiky. Report as a negative finding with its mechanism, or add a level-shift pattern (outside the 3×3)? — *Which?*
6. **Remaining:** seasonal C3 (running), steady row (C1, C2, C3), PP2 demo, analysis scripts/figures, thesis draft.
