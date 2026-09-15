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
  `layer_comparison_spiky.png`. This synthetic demo does not measure P95/P99
  latency, cold starts, or cost per request.
- Next step: validate the layers against real CloudWatch/Locust data.
