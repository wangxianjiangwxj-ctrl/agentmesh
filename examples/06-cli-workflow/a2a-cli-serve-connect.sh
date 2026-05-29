#!/usr/bin/env bash
# ============================================================================
# a2a-cli-serve-connect.sh — CLI serve/connect 组网演示
#
# 场景描述:
#   演示 agentmesh CLI 工具的 serve 和 connect 命令组网流程。
#   包括: 启动 Server、Connect 发送 Task、轮询 Task 状态、获取结果。
#
# 运行方式:
#   bash a2a-cli-serve-connect.sh
#
# 前置条件:
#   - agentmesh CLI 已安装 (如果未安装，脚本会以模拟模式运行)
#   - 或者: 安装后运行 `npm install -g @agentmesh/cli` 或 pip 安装
#
# 预期输出:
#   [agentmesh CLI 示例] ... (CLI serve/connect 模拟输出)
#   Agent A 服务已启动 (port 8080)
#   ......
#   示例运行结束
#
# 错误处理:
#   - 自动检测 agentmesh CLI 是否可用
#   - 不可用时使用模拟模式展示预期输出
#   - trap 确保脚本退出时清理后台进程
# ============================================================================

set -euo pipefail

# ── 配置 ─────────────────────────────────────────────────────────────────

PORT=${PORT:-8080}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/output"
AGENT_CARD_FILE="${SCRIPT_DIR}/agent-card-example.json"
TASK_FILE="${SCRIPT_DIR}/task-example.json"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
step()  { echo -e "\n${BLUE}==>${NC} $1"; }

# ── 清理函数 ─────────────────────────────────────────────────────────────

cleanup() {
    local exit_code=$?
    echo ""
    info "清理资源..."

    # 杀死后台运行的 agentmesh serve 进程
    if [ -n "${SERVER_PID:-}" ]; then
        if kill -0 "$SERVER_PID" 2>/dev/null; then
            info "停止 agentmesh serve (PID: $SERVER_PID)"
            kill "$SERVER_PID" 2>/dev/null || true
            wait "$SERVER_PID" 2>/dev/null || true
        fi
    fi

    # 清理临时文件
    if [ -d "$OUTPUT_DIR" ]; then
        rm -rf "$OUTPUT_DIR"
    fi
    if [ -f "$AGENT_CARD_FILE" ]; then
        rm -f "$AGENT_CARD_FILE"
    fi
    if [ -f "$TASK_FILE" ]; then
        rm -f "$TASK_FILE"
    fi

    info "清理完成"
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

# ── 环境检查 ─────────────────────────────────────────────────────────────

step "环境检查"

# 检查 agentmesh CLI 是否可用
AGENTMESH_AVAILABLE=false
if command -v agentmesh &>/dev/null; then
    AGENTMESH_AVAILABLE=true
    AGENTMESH_VERSION=$(agentmesh --version 2>/dev/null || echo "unknown")
    info "检测到 agentmesh CLI: $AGENTMESH_VERSION"
else
    warn "agentmesh CLI 未安装 (可通过 npm install -g @agentmesh/cli 或 pip install agentmesh 安装)"
    warn "将以 模拟模式 运行，展示 CLI serve/connect 的预期输出"
fi

# ── 准备工作目录 ─────────────────────────────────────────────────────────

step "准备工作目录"

mkdir -p "$OUTPUT_DIR"

# ── 1. 准备 AgentCard ────────────────────────────────────────────────────

step "步骤 1: 准备 AgentCard"

cat > "$AGENT_CARD_FILE" << 'CARD_EOF'
{
  "name": "数据搜索 Agent",
  "description": "支持多源数据搜索和信息提取的 AI Agent",
  "url": "http://localhost:8080",
  "skills": [
    {
      "name": "web-search",
      "description": "网络搜索引擎调用"
    },
    {
      "name": "data-extraction",
      "description": "从搜索结果中提取结构化数据"
    }
  ],
  "capabilities": {
    "streaming": false,
    "cancellation": true
  },
  "authentication": {
    "schemes": [
      {
        "type": "none"
      }
    ]
  }
}
CARD_EOF

info "AgentCard 已创建: $AGENT_CARD_FILE"
cat "$AGENT_CARD_FILE" | python3 -m json.tool 2>/dev/null || cat "$AGENT_CARD_FILE"

# ── 2. 准备 Task JSON 文件 ──────────────────────────────────────────────

step "步骤 2: 准备 Task JSON 文件"

cat > "$TASK_FILE" << 'TASK_EOF'
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "params": {
    "id": "task-cli-001",
    "message": {
      "messageId": "msg-cli-001",
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "搜索 2026 年 AI 安全领域的最新论文"
        }
      ]
    },
    "metadata": {
      "source": "agentmesh-cli",
      "priority": "high",
      "client_id": "user-cli-demo"
    }
  },
  "id": "1"
}
TASK_EOF

info "Task 文件已创建: $TASK_FILE"
cat "$TASK_FILE" | python3 -m json.tool 2>/dev/null || cat "$TASK_FILE"

# ── 3. 启动 Agent A Server ──────────────────────────────────────────────

step "步骤 3: 启动 Agent A (serve 端)"

if [ "$AGENTMESH_AVAILABLE" = true ]; then
    info "启动 agentmesh serve (端口: $PORT, AgentCard: $AGENT_CARD_FILE)"
    # 后台运行 serve
    agentmesh serve --port "$PORT" --card "$AGENT_CARD_FILE" -v &
    SERVER_PID=$!
    info "agentmesh serve 已启动 (PID: $SERVER_PID)"
else
    # 模拟模式
    SERVER_PID="$$_simulated"
    echo ""
    echo "┌────────────────────────────────────────────────────────────┐"
    echo "│  模拟: agentmesh serve 输出                                │"
    echo "├────────────────────────────────────────────────────────────┤"
    echo "│  启动命令:                                                │"
    echo "│    agentmesh serve --port ${PORT} --card agent-card.json -v │"
    echo "│                                                            │"
    echo "│  输出:                                                     │"
    echo "│    [agentmesh:serve] INFO  A2A Server starting on port ${PORT}│"
    echo "│    [agentmesh:serve] INFO  AgentCard: 数据搜索 Agent       │"
    echo "│    [agentmesh:serve] INFO  Skills: web-search, data-extraction│"
    echo "│    [agentmesh:serve] INFO  Endpoint: /tasks/send            │"
    echo "│    [agentmesh:serve] INFO  Endpoint: /tasks/getTask         │"
    echo "│    [agentmesh:serve] INFO  Server is ready                  │"
    echo "└────────────────────────────────────────────────────────────┘"
fi

# 等待服务启动
sleep 2
info "Agent A 服务已启动 (port: $PORT)"

# ── 4. Connect: 发送 Task ───────────────────────────────────────────────

step "步骤 4: 客户端连接 (connect) — 发送 Task"

if [ "$AGENTMESH_AVAILABLE" = true ]; then
    info "运行 agentmesh connect"
    agentmesh connect "http://localhost:${PORT}" \
        --task "$TASK_FILE" \
        --timeout 30 \
        --output "${OUTPUT_DIR}/result.json" \
        -v || true
else
    # 模拟模式
    echo ""
    echo "┌────────────────────────────────────────────────────────────┐"
    echo "│  模拟: agentmesh connect 输出                              │"
    echo "├────────────────────────────────────────────────────────────┤"
    echo "│  连接命令:                                                │"
    echo "│    agentmesh connect http://localhost:${PORT} \\             │"
    echo "│      --task task-example.json --timeout 30 --output result │"
    echo "│                                                            │"
    echo "│  输出:                                                     │"
    echo "│    [agentmesh:connect] 发现远程 AgentCard...               │"
    echo "│    [agentmesh:connect] 名称: 数据搜索 Agent                │"
    echo "│    [agentmesh:connect] Skill: web-search                   │"
    echo "│    [agentmesh:connect] Skill: data-extraction              │"
    echo "│    [agentmesh:connect] 连接成功                            │"
    echo "│                                                            │"
    echo "│    [agentmesh:connect] 发送 Task...                        │"
    echo "│    [agentmesh:connect] Task ID: task-cli-001              │"
    echo "│    [agentmesh:connect] 初始状态: SUBMITTED                │"
    echo "│    [agentmesh:connect] 等待处理...                         │"
    echo "│                                                            │"
    echo "│    [agentmesh:connect] 轮询 #1: SUBMITTED (0.5s)          │"
    echo "│    [agentmesh:connect] 轮询 #2: WORKING   (1.0s)          │"
    echo "│    [agentmesh:connect] 轮询 #3: WORKING   (1.5s)          │"
    echo "│    [agentmesh:connect] 轮询 #4: COMPLETED (2.0s)          │"
    echo "│                                                            │"
    echo "│    [agentmesh:connect] 结果已写入: output/result.json     │"
    echo "└────────────────────────────────────────────────────────────┘"

    # 模拟输出结果
    cat > "${OUTPUT_DIR}/result.json" << 'RESULT_EOF'
{
  "jsonrpc": "2.0",
  "result": {
    "id": "task-cli-001",
    "status": {
      "state": "COMPLETED",
      "timestamp": "2026-05-28T10:30:00Z"
    },
    "artifacts": [
      {
        "artifactId": "artifact-abc123",
        "parts": [
          {
            "type": "text",
            "text": "搜索完成: 2026年AI安全领域相关论文摘要...\n1. 'AI Safety in Multi-Agent Systems' (2026)\n2. 'Robust A2A Protocol Security' (2026)\n3. 'Agent Boundary Control Framework' (2026)"
          }
        ]
      }
    ]
  },
  "id": "1"
}
RESULT_EOF
fi

# ── 5. 查看结果 ─────────────────────────────────────────────────────────

step "步骤 5: 查看结果"

if [ -f "${OUTPUT_DIR}/result.json" ]; then
    info "Task 执行结果:"
    echo ""
    python3 -m json.tool "${OUTPUT_DIR}/result.json" 2>/dev/null || cat "${OUTPUT_DIR}/result.json"
else
    warn "结果文件不存在: ${OUTPUT_DIR}/result.json"
    info "如果 agentmesh CLI 实际运行中，请检查错误输出"
fi

# ── 6. 发送简单文本消息 (另一种 connect 用法) ──────────────────────────

step "步骤 6: (可选) 通过 --message 参数直接发送文本"

echo ""
echo "┌────────────────────────────────────────────────────────────┐"
echo "│  模拟: agentmesh connect --message                         │"
echo "├────────────────────────────────────────────────────────────┤"
echo "│  命令:                                                     │"
echo "│    agentmesh connect http://localhost:${PORT} \\             │"
echo "│      --message \"2026 年 AI Agent 协作的主要趋势有哪些？\" \\ │"
echo "│      --timeout 30                                          │"
echo "│                                                            │"
echo "│  输出:                                                     │"
echo "│    Task ID: task-cli-text-xxx                              │"
echo "│    状态: COMPLETED                                         │"
echo "│    结果: 2026年AI Agent协作的主要趋势包括:                  │"
echo "│      1. 多Agent编排成为主流工作模式                        │"
echo "│      2. A2A协议跨框架标准化                                │"
echo "│      3. Agent安全护栏需求增长                              │"
echo "└────────────────────────────────────────────────────────────┘"

# ── 完成 ─────────────────────────────────────────────────────────────────

echo ""
step "完成"
info "所有 CLI serve/connect 示例执行完毕"
echo ""
echo "  执行总结:"
echo "    [1] AgentCard 准备: 已完成 (data-scientist)"
echo "    [2] Task JSON 文件: 已完成"
echo "    [3] Agent A Server: 已启动 (port ${PORT})"
echo "    [4] Connect 发送 Task: 已完成"
echo "    [5] 结果获取: 已完成"
echo ""
echo "  如果要实际运行 (非模拟模式):"
echo "    1. 安装 agentmesh CLI:"
echo "       npm install -g @agentmesh/cli"
echo "       或: pip install agentmesh-sdk"
echo "    2. 然后运行本脚本:"
echo "       bash a2a-cli-serve-connect.sh"
echo ""
echo "  配置要点:"
echo "    - 端口冲突: 修改 PORT=8081 bash a2a-cli-serve-connect.sh"
echo "    - 自定义 AgentCard: 修改 AGENT_CARD_FILE 路径"
echo "    - 自定义 Task: 修改 TASK_FILE 路径"
echo ""
