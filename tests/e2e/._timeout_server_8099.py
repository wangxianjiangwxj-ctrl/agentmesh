import os
import sys

sys.path.insert(0, '/Users/wangxianjiang/.openclaw/workspace/shangshuling/agentmesh/tests/e2e/../..')

from agentmesh.a2a_models import ServerTimeoutConfig
from agentmesh.a2a_server import _build_app

cfg = ServerTimeoutConfig(
    request_timeout=3.0,
    stream_idle_timeout=5.0,
    connect_timeout=2.0,
    read_timeout=5.0,
)
app = _build_app(timeout_config=cfg)

import uvicorn

uvicorn.run(app, host="0.0.0.0", port=8099, log_level="warning")
