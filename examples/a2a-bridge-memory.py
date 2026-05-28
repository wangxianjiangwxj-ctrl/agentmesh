#!/usr/bin/env python3
"""
AgentMesh A2A Bridge — MemoryProvider 两Agent通信示例

展示：
  - 通过 MemoryProvider 在单进程中连接两个 Agent（bot-alpha, bot-beta）
  - bot-alpha 发送 TaskRequest -> bot-beta 接收并处理 -> 返回 TaskResult
  - 保真度追踪链、A2ATaskManager 状态机、A2AFacade 统一入口

运行方式（独立可运行）:
  python3 a2a-bridge-memory.py
"""

import sys, os, json, uuid
from datetime import datetime, timezone

# SDK路径：从 examples/ 到 sdk/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'sdk'))

from a2a_provider import (
    A2AProvider, MemoryProvider, A2AFacade,
    A2ATaskManager, A2ATaskState, A2AResult, A2AError,
)

# AgentMesh SDK — 保真度追踪
sys.path.insert(0, os.path.expanduser('~/.openclaw/skills/agentmesh-protocol/'))
try:
    from agentmesh_sdk import FidelityTracker, validate_message
    AGENTMESH_SDK = True
except ImportError:
    AGENTMESH_SDK = False


# ============================================================
# 消息 ID 生成
# ============================================================

def make_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ============================================================
# 1. 自定义 Provider：带回调的 MemoryProvider
# ============================================================

class CallbackMemoryProvider(MemoryProvider):
    """
    扩展 MemoryProvider，支持消息路由回调。
    当 send_message 调用时触发 on_message 回调，
    使 "接收方" Agent 能处理消息并产生响应。
    """

    def __init__(self, name: str = "callback-memory"):
        super().__init__(name)
        self.on_message = None  # callback(task) -> response_task

    def send_message(self, task: dict, auth=None) -> A2AResult:
        # 先存储任务
        result = super().send_message(task, auth)
        if not result.success:
            return result

        # 触发回调
        if self.on_message:
            try:
                response = self.on_message(task)
                if response:
                    self._tasks[response.get("id", "")] = response
            except Exception as e:
                return A2AResult.fail(A2AError(500, f"Callback error: {e}"))

        return result


# ============================================================
# 2. bot-alpha: 任务请求方
# ============================================================

def build_task_request() -> dict:
    """构造 A2A TaskRequest"""
    task_id = make_id("task")
    return {
        "id": task_id,
        "jsonrpc": "2.0",
        "method": "tasks.send",
        "params": {
            "id": task_id,
            "status": {"state": A2ATaskState.SUBMITTED},
            "messages": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "请分析2025年AI Agent安全领域的三大趋势："},
                        {"text": "1. 供应链安全攻击面"},
                        {"text": "2. 多Agent通信加密"},
                        {"text": "3. 权限管理与隔离"},
                    ],
                    "metadata": {
                        "agentmesh_sender": "bot-alpha",
                        "agentmesh_confidence": 0.9,
                        "agentmesh_fidelity": 1.0,
                        "agentmesh_schema_version": "2.1",
                    },
                }
            ],
        },
    }


# ============================================================
# 3. bot-beta: 任务处理方
# ============================================================

def process_task(task: dict) -> dict:
    """bot-beta 处理收到的 TaskRequest，构造 TaskResult"""
    task_id = task.get("id", "") or task.get("params", {}).get("id", "")
    params = task.get("params", task)  # 兼容两种格式

    # 提取请求消息
    messages = params.get("messages", [])
    request_text = ""
    for msg in messages:
        for part in msg.get("parts", []):
            request_text += part.get("text", "")

    # 模拟分析处理
    result_text = (
        "2025年AI Agent安全三大趋势分析：\n\n"
        "1. 供应链安全攻击面扩展：\n"
        "   - 第三方Plugin/Tool注入攻击同比增长120%\n"
        "   - Agent间依赖关系引入供应链攻击新向量\n"
        "   - 建议：实施运行时行为监控 + 数字签名校验\n\n"
        "2. 多Agent通信加密标准化：\n"
        "   - A2A协议v1.0已内置端到端加密支持\n"
        "   - TLS 1.3 + mTLS成为通信层标准\n"
        "   - 建议：所有跨Agent通信启用加密通道\n\n"
        "3. 权限管理与隔离机制成熟化：\n"
        "   - 基于RBAC/ABAC的Agent权限模型\n"
        "   - 沙箱隔离从进程级升级到容器级\n"
        "   - 建议：最小权限原则 + 审计日志全覆盖\n\n"
        "--- bot-beta 分析完毕 ---"
    )

    response_id = make_id("resp")
    response_task = {
        "id": task_id,
        "jsonrpc": "2.0",
        "method": "tasks.send",
        "params": {
            "id": task_id,
            "status": {"state": A2ATaskState.COMPLETED},
            "messages": [
                {
                    "role": "agent",
                    "parts": [{"text": result_text}],
                    "metadata": {
                        "agentmesh_sender": "bot-beta",
                        "agentmesh_confidence": 0.85,
                        "agentmesh_fidelity": 0.82,
                        "agentmesh_schema_version": "2.1",
                        "response_to": messages[0].get("metadata", {}).get("agentmesh_sender", "unknown")
                        if messages else "unknown",
                    },
                }
            ],
            "artifacts": [
                {
                    "id": make_id("art"),
                    "name": "security-trends-2025",
                    "parts": [
                        {
                            "text": json.dumps({
                                "supply_chain_risk": "high",
                                "encryption_status": "standardizing",
                                "permission_maturity": "maturing",
                            }, indent=2),
                            "mimeType": "application/json",
                        }
                    ],
                }
            ],
        },
    }
    return response_task


# ============================================================
# 4. 状态机演示
# ============================================================

def demo_state_machine():
    """展示 A2ATaskManager 状态机流转"""
    print()
    print("  [状态机演示]")
    mgr = A2ATaskManager()
    task_id = "sm_demo_001"

    # 追踪并逐步状态转移
    mgr.track(task_id, A2ATaskState.PENDING)
    states = [
        A2ATaskState.SUBMITTED,
        A2ATaskState.WORKING,
        A2ATaskState.COMPLETED,
    ]
    for state in states:
        ok = mgr.update_state(task_id, state)
        t = mgr.get_task(task_id)
        print(f"    {A2ATaskState.PENDING} -> {state}: {'OK' if ok else 'FAIL'}")
        print(f"      当前状态: {t['state']}")

    # 非法转换测试
    try:
        mgr.update_state(task_id, A2ATaskState.WORKING)
        print("    (非法转换未被拦截 — 异常)")
    except A2AError as e:
        print(f"    COMPLETED -> WORKING 被正确拦截: {e}")

    # 上下游追踪
    mgr.track("parent_x", A2ATaskState.SUBMITTED)
    mgr.track("child_a", A2ATaskState.PENDING, parent_id="parent_x")
    mgr.track("child_b", A2ATaskState.PENDING, parent_id="parent_x")
    children = mgr.get_children("parent_x")
    print(f"    上下游追踪: parent_x -> children = {[c['task_id'] for c in children]}")


# ============================================================
# 5. 主流程
# ============================================================

def main():
    print("=" * 65)
    print("AgentMesh A2A Bridge — MemoryProvider 两Agent通信")
    print("=" * 65)
    print()

    # ---- 5a. 创建 Provider + Facade ----
    print("[初始化]")
    provider = CallbackMemoryProvider("a2a-memory-bridge")
    task_manager = A2ATaskManager()
    facade = A2AFacade(provider=provider, task_manager=task_manager)
    print("  MemoryProvider       : a2a-memory-bridge")
    print("  A2ATaskManager       : 已创建")
    print("  A2AFacade            : 已创建")
    print()

    # 注册 Agent Cards
    provider.register_agent_card({
        "name": "bot-alpha",
        "description": "任务请求Agent，发起A2A TaskRequest",
        "capabilities": ["task-request"],
    })
    provider.register_agent_card({
        "name": "bot-beta",
        "description": "任务处理Agent，处理TaskRequest并返回TaskResult",
        "capabilities": ["task-processing", "analysis"],
    })

    # ---- 5b. 设置路由回调 ----
    print("[路由配置]")
    provider.on_message = lambda task: process_task(task)
    print("  bot-alpha -> MemoryProvider -> bot-beta (回调路由)")
    print()

    # ---- 5c. 保真度追踪 ----
    if AGENTMESH_SDK:
        tracker = FidelityTracker(warning_threshold=0.5)
        print("[保真度追踪]  已启用 (FidelityTracker)")
    else:
        print("[保真度追踪]  agentmesh_sdk 不可用，跳过追踪")
    print()

    # ---- 5d. bot-alpha 发送 TaskRequest ----
    print("[Step 1] bot-alpha 发送 TaskRequest")
    request_task = build_task_request()
    task_id = request_task.get("params", {}).get("id", "")
    print(f"  Task ID  : {task_id}")
    print(f"  方法     : {request_task.get('method')}")
    print(f"  状态     : {request_task['params']['status']['state']}")
    print(f"  消息数   : {len(request_task['params']['messages'])}")
    for msg in request_task["params"]["messages"]:
        meta = msg.get("metadata", {})
        print(f"  发送者   : {meta.get('agentmesh_sender', 'unknown')}")
        print(f"  保真度   : {meta.get('agentmesh_fidelity', 'N/A')}")
        print(f"  置信度   : {meta.get('agentmesh_confidence', 'N/A')}")
        print(f"  消息内容 : {msg['parts'][0]['text'][:80]}...")
    print()

    # 通过 Facade 发送（内部自动追踪任务并更新状态为 SUBMITTED）
    facade.send_task(request_task["params"])
    # 手动更新为 WORKING 以演示状态机流转
    task_manager.update_state(task_id, A2ATaskState.WORKING)
    print(f"  状态机更新: SUBMITTED -> WORKING")
    print()

    # 保真度追踪 — Step 1
    if AGENTMESH_SDK:
        tracker.add_step("bot-alpha", 1.0, "发送TaskRequest")

    # ---- 5e. bot-beta 处理 ----
    print("[Step 2] bot-beta 接收并处理...")
    response_task = process_task(request_task)
    resp_params = response_task["params"]
    print(f"  响应Task ID : {resp_params['id']}")
    print(f"  最终状态     : {resp_params['status']['state']}")
    for msg in resp_params["messages"]:
        meta = msg.get("metadata", {})
        print(f"  回复者       : {meta.get('agentmesh_sender', 'unknown')}")
        print(f"  响应保真度   : {meta.get('agentmesh_fidelity', 'N/A')}")
        print(f"  响应置信度   : {meta.get('agentmesh_confidence', 'N/A')}")
        # 打印结果摘要
        summary = msg["parts"][0]["text"]
        lines = summary.strip().split("\n")
        print(f"  结果摘要     : {lines[0]}")
        for line in lines[1:4]:
            print(f"                {line}")
    print(f"  Artifacts    : {len(resp_params.get('artifacts', []))} 个")
    for art in resp_params.get("artifacts", []):
        print(f"    - {art['name']} ({art['parts'][0].get('mimeType', 'text')})")
    print()

    # 状态机更新
    task_manager.update_state(task_id, A2ATaskState.COMPLETED)
    t = task_manager.get_task(task_id)
    print(f"  状态机更新: WORKING -> COMPLETED")
    print(f"  最终状态   : {t['state']}")
    print()

    # 保真度追踪 — Step 2
    if AGENTMESH_SDK:
        tracker.add_step("bot-beta", 0.82, "处理TaskRequest并返回TaskResult")

    # ---- 5f. 保真度报告 ----
    print("[Step 3] 保真度追踪报告")
    if AGENTMESH_SDK:
        print(f"  累积保真度     : {tracker.cumulative_fidelity:.4f}")
        print(f"  警告阈值       : {tracker.warning_threshold}")
        print(f"  警告触发       : {tracker.warning_triggered}")
        for step in tracker.chain:
            print(f"  Step {step['step']}: {step['agent']} 保真度={step['fidelity_self']} — {step['note']}")
    print()

    # ---- 5g. 状态机演示 ----
    print("[Step 4] A2ATaskManager 状态机")
    demo_state_machine()
    print()

    # ---- 5h. 验证 ----
    print("[Step 5] 通过 Facade 查询任务")
    r = facade.get_task(task_id)
    if r.success:
        print(f"  Facade.get_task({task_id}) = 成功")
        print(f"  任务状态    : {r.task_state}")
        print(f"  数据存在    : {r.data is not None}")
    else:
        print(f"  Facade.get_task({task_id}) = 失败: {r.error}")

    # 通过 Provider 查询 Agent Cards
    for name in ["bot-alpha", "bot-beta"]:
        card = provider.get_agent_card(name)
        if card:
            print(f"  Agent Card  : {card['name']} — {card['description']}")
    print()

    # ---- 5i. 汇总 ----
    print("=" * 65)
    print("通信完成 — 两Agent成功通过MemoryProvider桥接")
    print("=" * 65)
    print()
    print("传递链路: bot-alpha -> [MemoryProvider] -> bot-beta")
    print(f"Task ID : {task_id}")
    if AGENTMESH_SDK:
        print(f"累积保真度: {tracker.cumulative_fidelity:.4f}")
    print()
    print("注意: 此示例使用 MemoryProvider 在单进程中模拟")
    print("      A2A 通信，无需网络或外部 Server。")
    print("      对于跨进程/跨网络通信，请使用 HttpProvider。")
    print("      (参见 a2a-bridge-http.py)")
    print()


if __name__ == "__main__":
    main()
