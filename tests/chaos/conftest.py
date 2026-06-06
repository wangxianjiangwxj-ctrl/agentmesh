"""conftest: add platform/ to sys.path so test imports like `from db_schema import ...` work.

Matches the pattern used by tests/platform/conftest.py.
"""
import sys
from pathlib import Path

_platform_dir = str(Path(__file__).resolve().parents[2] / "agentmesh" / "platform")
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)
