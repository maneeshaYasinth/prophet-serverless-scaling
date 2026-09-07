"""
Condition 1: reactive baseline -- AWS Lambda's default scaling behavior with
no forecasting layer at all (or, optionally, AWS Application Auto Scaling's
target-tracking on ProvisionedConcurrencyUtilization, if you want a stronger
reactive baseline than pure default scaling).

This should require the least custom code: mostly measurement/logging around
an unmodified snip-infra deployment, run under the same three traffic patterns
as the other two conditions so results are comparable.
"""

# TODO: point this at snip-infra with no Provisioned Concurrency configured,
# run each traffic pattern (steady/spiky/seasonal) via src/data_generation/,
# and collect the same three metrics via src/evaluation/metrics.py.
