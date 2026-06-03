# 快速开始

5分钟上手 AgentMesh。

---

## 安装

```bash
pip install agentmesh
```

## 最小示例

```python
from agentmesh import CollaborationFlow

# 1. 创建协作流
flow = CollaborationFlow("AI Agent安全调研", use_signing=False)

# 2. 注册Agent
flow.register_agent("scout-alpha")
flow.register_agent("forge-beta")

# 3. A检索信息
flow.step_retrieval(
    "scout-alpha", "forge-beta",
    summary="检索到5条AI Agent安全相关研究",
    data={"sources": 5, "coverage": "2024-2025"},
    confidence=0.85,
    fidelity=0.9,
)

# 4. B整合报告
flow.step_integration(
    "forge-beta", "coordinator",
    summary="5条信息源整合：AI Agent安全研究方向综述",
    data={"key_findings": 4, "gaps": 2},
    confidence=0.78,
    fidelity=0.65,
)

# 5. 获取报告
report = flow.full_report()
print(f"冲突率: {report['validation']['conflict_rate']}%")
print(f"累积保真度: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
print(f"贡献度: {report['allocation']['shares']}")
```

## 输出

```
冲突率: 0.0%
累积保真度: 0.585
贡献度: {'scout-alpha': 0.5095, 'forge-beta': 0.4905}
```

**Aha Moment**: 2步传递后，累积保真度仅0.585——超过40%的信息在传递中丢失或变形。没有AgentMesh，你看不见这个衰减。

---

## CLI 使用

AgentMesh 提供 `agentmesh` 命令行工具。

```bash
# 初始化项目
agentmesh init

# 验证消息
agentmesh validate message.json

# A2A格式转换
agentmesh convert message.json --to a2a

# 保真度追踪
agentmesh fidelity chain.json

# 运行端到端流程
agentmesh run flow.json

# 启动A2A测试服务器
agentmesh serve

# 连接远程A2A服务器
agentmesh connect http://remote-host:8080
```

---

## A2A Test Server 示例

AgentMesh 内置了一个轻量级 A2A 测试服务器，可用于跨进程和跨语言的 Agent 通信测试。

### 启动服务器

```python
# 方式一：CLI启动
# agentmesh serve --port 8080

# 方式二：Python代码启动
from agentmesh.a2a_server import cmd_server

# 启动A2A测试服务器，监听 0.0.0.0:8080
cmd_server(port=8080)
```

启动后访问 http://localhost:8080/health 查看服务器状态。

### 连接服务器并发送任务

```python
from agentmesh.a2a_server import HttpProvider

# 创建HTTP客户端
client = HttpProvider("http://localhost:8080")

# 发送一个任务
task = {
    "id": "task_001",
    "status": {"state": "submitted"},
    "payload": {"text": "Hello, A2A Server!"},
}
result = client.send_message(task)
print(f"发送结果: {result.success}, 状态: {result.task_state}")

# 查询任务
result = client.get_task("task_001")
print(f"任务数据: {result.data}")

# 取消任务
result = client.cancel_task("task_001")
print(f"取消结果: {result.success}, 状态: {result.task_state}")
```

### SSE 流式订阅

服务器支持 Server-Sent Events (SSE)，可以实时订阅任务状态变化：

```python
from agentmesh.a2a_server import HttpProvider, SSEStream

client = HttpProvider("http://localhost:8080")

# 提交任务
task = {
    "id": "task_sse_001",
    "status": {"state": "submitted"},
    "payload": {"text": "Stream me"},
}
client.send_message(task)

# 通过SSE流式订阅状态变化
stream = SSEStream("http://localhost:8080", "task_sse_001")
for event_type, data in stream:
    print(f"[{event_type}] {data}")
    if event_type == "done":
        break
```

---

## 多轮会话示例

AgentMesh 支持通过 A2A Server 进行多轮会话，适合模拟连续对话场景。

```python
from agentmesh.a2a_server import HttpProvider

client = HttpProvider("http://localhost:8080")

task_id = "conversation_001"

# 第1轮：提交初始请求
task = {
    "id": task_id,
    "status": {"state": "submitted"},
    "payload": {"text": "请分析2024年AI趋势"},
    "metadata": {"rounds": 0, "history": []},
}
result = client.send_message(task)
print(f"第1轮: {result.success}")

# 第2轮：检查状态
result = client.get_task(task_id)
print(f"第2轮: 任务状态 = {result.data['status']['state']}")

# 第3轮：发送更新请求（模拟精化）
updated = {
    "id": task_id,
    "status": {"state": "submitted"},
    "payload": {"text": "聚焦大语言模型方向"},
    "metadata": {"rounds": 1, "history": [{"round": 1, "action": "submit"}]},
}
result = client.send_message(updated)
print(f"第3轮: {result.success}")

# 第4轮：最终查询并清理
result = client.get_task(task_id)
print(f"第4轮: 最终payload = {result.data['payload']}")

result = client.cancel_task(task_id)
print(f"清理: {result.success}")
```

---

## 日志与追踪

AgentMesh 内置结构化日志和分布式追踪能力。

```python
from agentmesh.a2a import StructuredLogger, LogLevel, LoggerConfig
from agentmesh.a2a import TraceProvider, with_trace_context

# 配置日志
StructuredLogger.configure(LoggerConfig(level=LogLevel.INFO, output="stdout"))

# 创建日志器
log = StructuredLogger("my-app")

# 在追踪上下文内记录日志
provider = TraceProvider()
with with_trace_context(provider.new_context()) as ctx:
    log.info("card_sent", detail="Task card dispatched", recipient="agent-b")
    log.info("card_received", detail="Response received", sender="agent-b")
```

---

## 下一步

- 查看[架构文档](architecture.md)了解系统设计
- 运行[完整示例](examples/01-two-agent-research.md)看场景演示
- 接入[A2A适配器](api/adapter.md)与A2A生态互操作
- 查看[A2A Test Server指南](a2a-test-server.md)了解测试服务器全部功能
- 阅读[API Reference](api-reference/index.md)了解各模块详细接口
