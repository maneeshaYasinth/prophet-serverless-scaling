"""
Layer 2: Confidence-Bound Scaling Trigger
==========================================

Instead of scaling Lambda Provisioned Concurrency to Prophet's point
forecast (yhat), this layer scales to the upper confidence bound
(yhat_upper). This deliberately trades some over-provisioning for a much
lower chance of under-provisioning on bursty / uncertain traffic.

This module is pure logic -- no AWS calls, no Prophet fitting -- so it can
be unit tested and reused by both the offline evaluation scripts and the
live controller in src/controller/.

Expects forecast data with at least: yhat, yhat_upper (a dict-like row,
e.g. a pandas Series from Prophet's forecast dataframe).
"""

import math


def _convert(forecast_value, capacity_model, requests_per_instance, min_concurrency, max_concurrency):
    if capacity_model is not None:
        return capacity_model.target(forecast_value)
    # Legacy placeholder conversion, kept for the synthetic-data demos only.
    target = math.ceil(max(forecast_value, 0) / requests_per_instance)
    target = max(target, min_concurrency)
    if max_concurrency is not None:
        target = min(target, max_concurrency)
    return target


def compute_target_concurrency(
    forecast_row,
    requests_per_instance=10,
    min_concurrency=1,
    max_concurrency=None,
    capacity_model=None,
):
    """
    Convert a forecasted *upper-bound* request rate into a target
    Provisioned Concurrency value.

    Args:
        forecast_row: dict/Series with a 'yhat_upper' field -- forecasted
            requests per second (or per interval) at the upper confidence
            bound.
        requests_per_instance: how many concurrent requests one Lambda
            instance is assumed to comfortably handle. This is a
            placeholder -- calibrate it from real Locust/CloudWatch load
            tests against snip-infra rather than guessing.
        min_concurrency: floor, so we never scale below this (avoids
            0-concurrency edge cases).
        max_concurrency: optional ceiling, e.g. your account's Provisioned
            Concurrency limit for the function.
        capacity_model: a calibrated src.controller.capacity_model.CapacityModel.
            When given, it replaces requests_per_instance and the min/max
            arguments (the model carries its own bounds).

    Returns:
        int: target provisioned concurrency.
    """
    return _convert(forecast_row["yhat_upper"], capacity_model, requests_per_instance, min_concurrency, max_concurrency)


def compute_point_forecast_concurrency(
    forecast_row,
    requests_per_instance=10,
    min_concurrency=1,
    max_concurrency=None,
    capacity_model=None,
):
    """
    Same idea, but using yhat (the point forecast) instead of yhat_upper.

    Not used by the enhanced condition -- this exists so the vanilla-Prophet
    comparison condition, and the over-provisioning-gap analysis, share the
    exact same conversion logic as the enhanced condition. That keeps the
    comparison fair: any difference in provisioned capacity comes from
    which forecast field is used, not from a different formula.
    """
    return _convert(forecast_row["yhat"], capacity_model, requests_per_instance, min_concurrency, max_concurrency)
