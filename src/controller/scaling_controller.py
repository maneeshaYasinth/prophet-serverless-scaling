"""
Enhanced Scaling Controller
============================

Ties Layer 2 (confidence-bound trigger) and Layer 3 (Z-score anomaly
detection) together into a single per-interval scaling decision. This is
the core decision logic for the "Enhanced Prophet" experimental condition.

Per the repo's intended layout (src/controller/ = a separate process that
calls the Provisioned Concurrency API based on forecast output), this
module is deliberately AWS-agnostic: it takes forecast/actual data in and
returns a target concurrency out. Wire the actual boto3 call
(`put_provisioned_concurrency_config`) in a thin wrapper around `decide()`
so this decision logic stays unit-testable without AWS credentials.

Example of the thin AWS wrapper you'd add later (not included here, since
it needs live credentials):

    import boto3
    client = boto3.client("lambda")

    def apply_decision(function_name, qualifier, decision):
        client.put_provisioned_concurrency_config(
            FunctionName=function_name,
            Qualifier=qualifier,
            ProvisionedConcurrentExecutions=decision["target_concurrency"],
        )
"""

import sys
import os

# Allow running this module directly for local testing without a package install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.forecasting.confidence_bound_trigger import compute_target_concurrency
from src.forecasting.anomaly_detector import ZScoreAnomalyDetector


class EnhancedScalingController:
    def __init__(
        self,
        requests_per_instance=10,
        min_concurrency=1,
        max_concurrency=None,
        z_window_size=30,
        z_threshold=2.0,
    ):
        self.requests_per_instance = requests_per_instance
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.anomaly_detector = ZScoreAnomalyDetector(
            window_size=z_window_size, z_threshold=z_threshold
        )
        self.log = []

    def decide(self, forecast_row, actual=None):
        """
        Args:
            forecast_row: dict/Series with 'yhat' and 'yhat_upper' for the
                current time step (Layer 2 input).
            actual: the most recently observed actual traffic value, if
                available (Layer 3 input). Pass None if not yet known.

        Returns:
            dict with the chosen target_concurrency, which layer drove the
            decision ("layer2_confidence_bound" or "layer3_zscore_override"),
            and diagnostic fields -- ready to append to a results CSV or
            docs/EXPERIMENT_LOG.md.
        """
        decision = {
            "ds": forecast_row.get("ds"),
            "yhat": forecast_row.get("yhat"),
            "yhat_upper": forecast_row.get("yhat_upper"),
            "actual": actual,
        }

        anomaly_info = None
        if actual is not None:
            anomaly_info = self.anomaly_detector.update_and_check(
                actual, forecast_row["yhat"]
            )
            decision.update(anomaly_info)

        if anomaly_info and anomaly_info["is_anomaly"]:
            target = self.anomaly_detector.emergency_target_concurrency(
                actual,
                requests_per_instance=self.requests_per_instance,
                min_concurrency=self.min_concurrency,
            )
            decision["target_concurrency"] = target
            decision["triggered_by"] = "layer3_zscore_override"
        else:
            target = compute_target_concurrency(
                forecast_row,
                requests_per_instance=self.requests_per_instance,
                min_concurrency=self.min_concurrency,
                max_concurrency=self.max_concurrency,
            )
            decision["target_concurrency"] = target
            decision["triggered_by"] = "layer2_confidence_bound"

        self.log.append(decision)
        return decision

    def activation_summary(self):
        """
        Counts of how often each layer drove the scaling decision -- this
        is exactly the "layer activation logging" secondary analysis your
        supervisor asked for, without needing a full ablation study.
        """
        total = len(self.log)
        z_fires = sum(
            1 for d in self.log if d["triggered_by"] == "layer3_zscore_override"
        )
        return {
            "total_decisions": total,
            "layer2_confidence_bound_count": total - z_fires,
            "layer3_zscore_override_count": z_fires,
        }
