#!/usr/bin/env bash
# AgentMesh 本地一键 Demo 环境
# 用法: ./demo/run.sh [server|client|full]
#
# 无需网络，无需安装额外依赖 (stdlib + fastapi/uvicorn)
# 自动初始化 SQLite DB + 启动 Demo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEMO_DIR="$SCRIPT_DIR"

echo "=== AgentMesh Demo 环境 ==="
echo ""

cleanup() {
    echo ""
    echo "关闭 Demo 环境..."
    [ -n "${SERVER_PID:-}" ] && kill "$SERVER_PID" 2>/dev/null || true
    echo "已清理。"
}
trap cleanup EXIT

case "${1:-full}" in
    server)
        echo "[启动] A2A 测试服务器 (http://localhost:8080)"
        echo "        文档: http://localhost:8080/docs"
        cd "$PROJECT_DIR"
        python -m agentmesh.a2a_server server &
        SERVER_PID=$!
        wait
        ;;
    client)
        echo "[运行] Demo 工作流客户端"
        cd "$PROJECT_DIR"
        python "$DEMO_DIR/demo_workflow.py"
        ;;
    full|*)
        echo "[Step 1/3] 启动 A2A 服务器 (后台)..."
        cd "$PROJECT_DIR"
        python -m agentmesh.a2a_server server &
        SERVER_PID=$!
        sleep 2

        echo "[Step 2/3] 运行 Demo 工作流..."
        python "$DEMO_DIR/demo_workflow.py"

        echo "[Step 3/3] 停止服务器..."
        kill "$SERVER_PID" 2>/dev/null || true
        echo ""
        echo "=== Demo 完成 ==="
        ;;
esac
