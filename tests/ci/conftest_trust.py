"""Test configuration — add the parent directory to sys.path for imports."""

import sys
from pathlib import Path

# Add the integration root to path so `from agentid_trust_provider import ...` works
sys.path.insert(0, str(Path(__file__).parent.parent))
