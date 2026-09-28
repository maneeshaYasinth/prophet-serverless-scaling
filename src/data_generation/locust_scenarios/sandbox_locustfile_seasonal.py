"""Run: locust -f sandbox_locustfile_seasonal.py --headless"""

from sandbox_user import LambdaInvokeUser  # noqa: F401
from shapes import SeasonalShape  # noqa: F401
