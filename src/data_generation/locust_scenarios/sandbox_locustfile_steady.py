"""Run: locust -f sandbox_locustfile_steady.py --headless"""

from sandbox_user import LambdaInvokeUser  # noqa: F401
from shapes import SteadyShape  # noqa: F401
