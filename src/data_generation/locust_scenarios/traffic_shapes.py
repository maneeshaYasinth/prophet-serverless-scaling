"""
Locust HTTP user for the eventual real snip-infra target (once it's confirmed
safe to point real load at it -- see sandbox_user.py for the boto3-invoke
version used against sandbox-lambda in the meantime).

Shape logic lives in shapes.py, shared with the boto3-invoke user so both
targets run identical traffic patterns.

Usage: locust -f traffic_shapes.py --headless
"""

from locust import HttpUser, task

from shapes import SeasonalShape, SpikyShape, SteadyShape  # noqa: F401  (re-exported for Locust's discovery)


class SnipInfraUser(HttpUser):
    @task
    def shorten_and_redirect(self):
        # TODO: point at your actual snip-infra endpoints, once you're ready
        # to move past sandbox-lambda validation.
        self.client.post("/shorten", json={"url": "https://example.com"})
