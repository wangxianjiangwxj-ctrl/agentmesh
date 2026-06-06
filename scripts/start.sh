#!/usr/bin/env bash
#
# AgentMesh Platform — Phase 21 Direction A
# Startup script: sets PYTHONPATH and launches the Gateway server.
#
# Usage:
#   ./scripts/start.sh                    # default :memory: DB
#   ./scripts/start.sh --db agentmesh.db  # persistent DB
#   ./scripts/start.sh --port 9000        # custom port
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export PYTHONPATH="${PYTHONPATH:-}:${PROJECT_ROOT}"

cd "$PROJECT_ROOT"

echo "[agentmesh] Starting AgentMesh Gateway..."
echo "[agentmesh] PYTHONPATH=${PYTHONPATH}"
echo "[agentmesh] CWD=$(pwd)"

exec python -m agentmesh.cli serve "$@"
