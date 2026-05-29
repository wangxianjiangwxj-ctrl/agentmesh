#!/usr/bin/env python3
"""
a2a-bridge-local.py — 两个本地 Agent 通过 A2A 协议直接桥接通信

场景描述:
    模拟 AgentMesh A2A 桥接的核心流程。两个 Agent (Scout 和 Analyst)
    在同一 Python 进程中通过内存通道 (MemoryProvider) 通信。
    不依赖外部 SDK 或网络，完全自包含。

Agent 角色:
    - Scout Agent (数据收集者): 模拟搜索和收集信息，输出结构化数据
    - Analyst Agent (分析师): 接收 Scout 的输出，进行分析并生成报告

运行方式:
    python a2a-bridge-local.py

预期输出:
    [Scout Agent] 已注册 AgentCard
    [Analyst Agent] 已注册 AgentCard
    发送任务: scout -> analyst
    ... (轮询进度)
    任务完成! Task ID: task-001
    状态: COMPLETED
    分析报告: ...
"""

import asyncio
import json
import time
import uuid
from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# 1. 核心枚举与类型定义
# ═══════════════════════════════════════════════════════════════

class A2ATaskState(str, Enum):
    """A2A Task 状态枚举 (符合 A2A 协议规范)"""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    WORKING = "WORKING"
    INPUT_REQUIRED = "INPUT_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


# ═══════════════════════════════════════════════════════════════
# 2. MemoryProvider — 模拟 A2A Server 的内存通道
# ═══════════════════════════════════════════════════════════════

class MemoryProvider:
    """
    内存通道 Provider。在进程内模拟 A2A JSON-RPC 通信。
    相当于一个简化版的内存 A2A Server。

    职责:
        - 存储 AgentCard 注册信息
        - 接收和存储 Task
        - 模拟任务处理 (状态转换)
        - 支持 task 查询 (轮询)
    """

    def __init__(self, name: str = "local-bridge"):
        self.name = name
        self._agent_cards: dict[str, dict] = {}     # url -> card
        self._tasks: dict[str, dict] = {}            # task_id -> task

    # ── 2.1 AgentCard 注册 ──

    def register_agent_card(self, card: dict) -> None:
        """注册一个 Agent 的能力描述卡"""
        url = card.get("url", f"memory://{card['name']}")
        self._agent_cards[url] = card
        name = card.get("name", "unknown")
        print(f"  [MemoryProvider] AgentCard 已注册: {name} @ {url}")

    def get_agent_card(self, url: str) -> Optional[dict]:
        """获取指定 URL 的 AgentCard"""
        return self._agent_cards.get(url)

    def discover_agents(self) -> list[dict]:
        """发现所有已注册的 Agent"""
        return list(self._agent_cards.values())

    # ── 2.2 Task 生命周期管理 (模拟 A2A tasks/send + tasks/getTask) ──

    async def send_task(self, task: dict) -> dict:
        """
        模拟 tasks/send JSON-RPC 调用。

        将任务放入内存存储，初始状态为 SUBMITTED，
        然后异步启动模拟处理。
        """
        task_id = task.get("id", f"task-{uuid.uuid4().hex[:8]}")
        task["id"] = task_id

        # 初始状态: SUBMITTED
        task["status"] = {
            "state": A2ATaskState.SUBMITTED.value,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        self._tasks[task_id] = task
        print(f"  [MemoryProvider] Task 已接收: {task_id} (状态: SUBMITTED)")

        # 异步启动模拟处理 (实际不会阻塞 send 调用)
        asyncio.create_task(self._simulate_processing(task_id))

        return {
            "jsonrpc": "2.0",
            "result": {
                "id": task_id,
                "status": task["status"],
            },
        }

    async def get_task(self, task_id: str) -> dict:
        """
        模拟 tasks/getTask JSON-RPC 调用。

        查询指定 task 的当前状态。轮询过程中反复调用此方法。
        """
        task = self._tasks.get(task_id)
        if not task:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32000,
                    "message": f"Task not found: {task_id}",
                },
            }

        return {
            "jsonrpc": "2.0",
            "result": {
                "id": task_id,
                "status": task.get("status", {}),
                "artifacts": task.get("artifacts", []),
            },
        }

    async def _simulate_processing(self, task_id: str) -> None:
        """
        模拟 A2A Server 端的任务处理。

        状态转换:
            SUBMITTED -> WORKING (1.5秒后)
            WORKING -> COMPLETED (2.5秒后，含分析结果)
        """
        task = self._tasks.get(task_id)
        if not task:
            return

        # Step 1: SUBMITTED -> WORKING (模拟 1.5s 分析耗时)
        await asyncio.sleep(1.5)
        task["status"] = {
            "state": A2ATaskState.WORKING.value,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        print(f"  [MemoryProvider] Task {task_id}: WORKING (分析进行中...)")

        # Step 2: WORKING -> COMPLETED (再模拟 2.5s)
        await asyncio.sleep(2.5)

        # 构造分析结果 (从原始消息的 payload 中提取数据)
        payload = task.get("agentmesh_payload", {})
        data = payload.get("data", {})
        extracted = data.get("extracted_content", {})

        key_points = extracted.get("key_points", [
            "AI Agent 协作成为主流",
            "A2A 协议标准化推进中",
            "多 Agent 编排需求增长",
        ])

        report_text = (
            "分析报告: 2026 AI 趋势\n"
            "======================\n"
            f"数据来源: {data.get('source', '未知')}\n"
            f"采集时间: {extracted.get('timestamp', '未知')}\n\n"
            "关键发现:\n"
        )
        for i, point in enumerate(key_points, 1):
            report_text += f"  {i}. {point}\n"

        report_text += "\n总结:\n"
        report_text += "  2026年AI领域呈现三大趋势: 多Agent自主协作成为新的工作范式,\n"
        report_text += "  A2A协议跨框架标准化进程加速, 企业对Agent编排平台的需求持续增长。\n"

        task["status"] = {
            "state": A2ATaskState.COMPLETED.value,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        task["artifacts"] = [
            {
                "artifactId": f"artifact-{uuid.uuid4().hex[:8]}",
                "parts": [
                    {
                        "type": "text",
                        "text": report_text,
                    }
                ],
            }
        ]
        print(f"  [MemoryProvider] Task {task_id}: COMPLETED (分析完成)")


# ═══════════════════════════════════════════════════════════════
# 3. A2AFacade — AgentMesh 的 A2A 桥接门面
# ═══════════════════════════════════════════════════════════════

class A2AFacade:
    """
    A2A 桥接门面。对外提供统一的 send_task 接口。
    内部处理:
        - AgentMesh 消息 -> A2A Task 转换
        - Provider 路由
        - Task 状态轮询
        - A2A Response -> AgentMesh 消息转换
    """

    def __init__(self, providers: list[MemoryProvider]):
        self._providers = providers

    async def send_task(
        self,
        agentmesh_msg: dict,
        target_url: str = "",
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> dict:
        """
        发送 AgentMesh 格式的消息，经过 A2A 桥接后返回结果。

        参数:
            agentmesh_msg: AgentMesh 消息字典
            target_url: 目标 Agent URL (如 "memory://analyst")
            timeout: 整体超时(秒)
            poll_interval: 轮询间隔(秒)

        返回:
            A2AResult 风格的字典
        """
        start_time = time.time()

        # ── 3.1 查找目标 Provider ──
        provider = self._select_provider(target_url)
        if not provider:
            return {
                "success": False,
                "error": {
                    "code": "PROVIDER_NOT_FOUND",
                    "message": f"没有找到可处理 {target_url} 的 Provider",
                    "recoverable": False,
                },
            }

        # ── 3.2 构造 A2A Task (模拟 A2AAdapterV2 转换) ──
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        task = {
            "id": task_id,
            "message": {
                "messageId": f"msg-{uuid.uuid4().hex[:8]}",
                "role": "user",
                "parts": [
                    {
                        "type": "text",
                        "text": agentmesh_msg.get("payload", {}).get("intent", ""),
                    }
                ],
            },
            "metadata": {
                "agentmesh_from": agentmesh_msg.get("from_agent", "unknown"),
                "agentmesh_to": agentmesh_msg.get("to_agent", "unknown"),
                "agentmesh_adapter_version": "v0.3-simulated",
            },
            "agentmesh_payload": agentmesh_msg.get("payload", {}),
        }

        print(f"\n  [A2AFacade] AgentMesh msg -> A2A Task 转换完成")
        print(f"  [A2AFacade] Task ID: {task_id}")
        print(f"  [A2AFacade] From: {task['metadata']['agentmesh_from']}")
        print(f"  [A2AFacade] To:   {task['metadata']['agentmesh_to']}")

        # ── 3.3 发送 Task ──
        provider.send_result = await provider.send_task(task)

        # ── 3.4 轮询 Task 直到完成或超时 ──
        poll_count = 0
        final_state = None

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                return {
                    "success": False,
                    "error": {
                        "code": "TIMEOUT",
                        "message": f"Task 轮询超时 (超过 {timeout}s)",
                        "recoverable": True,
                    },
                }

            await asyncio.sleep(poll_interval)
            poll_count += 1

            response = await provider.get_task(task_id)
            result = response.get("result", {})
            status = result.get("status", {})
            state = status.get("state", "")

            if poll_count % 3 == 0:  # 每3次打印一次轮询状态
                print(f"  [A2AFacade] 轮询 #{poll_count}: {state} ({elapsed:.1f}s)")

            if state in (A2ATaskState.COMPLETED.value, A2ATaskState.FAILED.value, A2ATaskState.CANCELED.value):
                final_state = state
                break

        # ── 3.5 处理最终结果 ──
        total_elapsed = (time.time() - start_time) * 1000  # ms

        if final_state == A2ATaskState.COMPLETED.value:
            artifacts = result.get("artifacts", [])
            # 提取分析报告文本
            report_text = ""
            for artifact in artifacts:
                for part in artifact.get("parts", []):
                    if part.get("type") == "text":
                        report_text += part.get("text", "")

            # 构造 AgentMesh 格式的响应消息
            agentmesh_response = {
                "message_type": "task_result",
                "from_agent": agentmesh_msg.get("to_agent", "unknown"),
                "to_agent": agentmesh_msg.get("from_agent", "unknown"),
                "payload": {
                    "report": report_text,
                    "artifact_count": len(artifacts),
                    "summary": f"分析报告 (来自 {agentmesh_msg.get('to_agent', 'unknown')})",
                },
            }

            return {
                "success": True,
                "task_id": task_id,
                "provider": provider.name,
                "a2a_task_state": final_state,
                "elapsed_ms": total_elapsed,
                "poll_count": poll_count,
                "agentmesh_message": agentmesh_response,
            }
        else:
            return {
                "success": False,
                "task_id": task_id,
                "provider": provider.name,
                "a2a_task_state": final_state,
                "elapsed_ms": total_elapsed,
                "error": {
                    "code": "TASK_FAILED",
                    "message": f"Task 结束状态: {final_state}",
                    "recoverable": final_state == A2ATaskState.FAILED.value,
                },
            }

    def _select_provider(self, target_url: str) -> Optional[MemoryProvider]:
        """根据 target URL 选择 Provider (简单匹配)"""
        if not self._providers:
            return None
        # 单 Provider 场景：直接返回第一个
        return self._providers[0]

    async def close(self):
        """资源清理"""
        pass


# ═══════════════════════════════════════════════════════════════
# 4. 主流程: Scout -> Analyst 通信
# ═══════════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  AgentMesh A2A 桥接示例 — 本地 Agent 直接通信")
    print("=" * 70)
    print()

    # ── 4.1 创建 MemoryProvider (模拟 A2A Server) ──
    print("[1] 创建 MemoryProvider...")
    memory = MemoryProvider(name="local-bridge")
    print()

    # ── 4.2 注册两个 Agent 的 AgentCard ──
    print("[2] 注册 Agent 能力卡 (AgentCard)...")

    scout_card = {
        "name": "scout-agent",
        "description": "信息收集 Agent，支持多源检索",
        "url": "memory://scout",
        "skills": [
            {"name": "web-search", "description": "网络搜索"},
            {"name": "data-extraction", "description": "数据提取"},
        ],
        "capabilities": {"streaming": False, "cancellation": True},
    }
    analyst_card = {
        "name": "analyst-agent",
        "description": "数据分析 Agent，支持结构化分析报告",
        "url": "memory://analyst",
        "skills": [
            {"name": "data-analysis", "description": "结构化数据分析"},
            {"name": "report-generation", "description": "报告生成"},
        ],
        "capabilities": {"streaming": True, "cancellation": True},
    }

    memory.register_agent_card(scout_card)
    memory.register_agent_card(analyst_card)
    print()

    # ── 4.3 创建 A2AFacade ──
    print("[3] 创建 A2A 桥接门面 (A2AFacade)...")
    facade = A2AFacade(providers=[memory])
    print()

    # ── 4.4 构造 AgentMesh 格式的消息 ──
    print("[4] 构造 AgentMesh 消息...")

    scout_message = {
        "message_type": "task",
        "from_agent": "scout-agent",
        "to_agent": "analyst-agent",
        "payload": {
            "intent": "分析以下数据并生成结构化报告",
            "data": {
                "source": "web-crawl",
                "urls": ["https://example.com/tech-news"],
                "extracted_content": {
                    "title": "2026 AI 趋势",
                    "key_points": [
                        "AI Agent 协作成为主流",
                        "A2A 协议标准化推进中",
                        "多 Agent 编排需求增长",
                    ],
                    "timestamp": "2026-05-28T00:00:00Z",
                },
            },
        },
        "fidelity": 0.95,
        "allocation": {
            "contributors": ["scout-agent"],
            "split_mode": "exact",
            "distribution": {"scout-agent": 1.0},
        },
    }

    print(f"  发送者: {scout_message['from_agent']}")
    print(f"  接收者: {scout_message['to_agent']}")
    print(f"  意图:   {scout_message['payload']['intent']}")
    print()

    # ── 4.5 通过 Facade 发送并获取结果 ──
    print("[5] 发送任务并等待分析结果...")
    print("-" * 50)

    result = await facade.send_task(
        agentmesh_msg=scout_message,
        target_url="memory://analyst",
        timeout=30.0,
    )

    print("-" * 50)
    print()

    # ── 4.6 输出结果 ──
    print("[6] 任务执行结果:")
    print("=" * 50)

    if result["success"]:
        print(f"  状态:     通过")
        print(f"  Task ID:  {result['task_id']}")
        print(f"  Provider: {result['provider']}")
        print(f"  最终状态: {result['a2a_task_state']}")
        print(f"  耗时:     {result['elapsed_ms']:.0f} ms")
        print(f"  轮询次数: {result['poll_count']}")

        agentmesh_response = result.get("agentmesh_message", {})
        payload = agentmesh_response.get("payload", {})
        report = payload.get("report", "")

        print(f"\n分析报告:")
        print(report)
    else:
        error = result.get("error", {})
        print(f"  状态:     失败")
        print(f"  错误码:   {error.get('code', 'N/A')}")
        print(f"  错误信息: {error.get('message', 'N/A')}")
        print(f"  可恢复:   {error.get('recoverable', False)}")

    # ── 4.7 资源清理 ──
    await facade.close()
    print()
    print("=" * 70)
    print("  示例运行结束")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
