"""Run: TRAFFIC_PATTERN=steady|spiky|seasonal locust -f sandbox_locustfile_patterns.py --headless"""

import sys
from pathlib import Path

# Import via the repo root, not src/data_generation/: this folder also has a
# traffic_shapes.py (the snip-infra HTTP user), which would shadow it.
sys.path.append(str(Path(__file__).resolve().parents[3]))

from sandbox_user import LambdaInvokeUser  # noqa: F401,E402
from src.data_generation.traffic_shapes import TrafficPatternShape  # noqa: F401,E402
