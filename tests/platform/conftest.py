"""conftest: add platform/ to sys.path so test imports like `from db_schema import ...` work.

All 5 platform test files use flat import paths (e.g. `from db_schema import create_test_db`)
which assume `platform/` is on sys.path. This conftest makes that work without modifying
each test file.
"""
import sys
from pathlib import Path

_platform_dir = str(Path(__file__).resolve().parents[2] / "agentmesh" / "platform")
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)
