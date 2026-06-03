# 从零搭建你的第一个 A2A Agent

> 目标读者：有 Python 基础但首次接触 AgentMesh
> 用时：约 30 分钟
> 难度：入门级

---

## 环境准备

### 前置条件

- Python >= 3.10
- pip 包管理器
- （可选）虚拟环境工具（venv / conda / poetry）

### 安装 AgentMesh

```bash
# 创建并进入虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows

# 安装 AgentMesh
pip install agentmesh

# 验证安装成功
python -c "import agentmesh; print(agentmesh.__version__)"
```

---

## 第一步：创建你的第一个 Agent

创建一个文件 `hello_agent.py`：

```python
from agentmesh import Agent

# 创建一个简单的 Agent，具备打招呼能力
agent = Agent(
    name="hellobot",
    description="一个会打招呼的机器人",
    system_prompt="你是一个友好的助手。当有人跟你打招呼时，热情回应。",
)

# 直接调用
result = agent.run("你好！我是小明。")
print(result)
```

运行：

```bash
python hello_agent.py
```

预期输出：

```
你好小明！很高兴认识你！我是 hellobot，有什么我可以帮你的吗？
```

---

## 第二步：让 Agent 拥有工具

AgentMesh 的核心能力：Agent 可以调用工具（Tools）。

创建一个文件 `weather_agent.py`：

```python
from agentmesh import Agent

# 模拟天气查询工具
def get_weather(city: str) -> str:
    """查询指定城市的天气。

    Args:
        city: 城市名称，如"北京"、"上海"

    Returns:
        该城市的天气信息
    """
    # 实际项目中替换为真实 API 调用
    weather_data = {
        "北京": "晴，25°C，空气质量良",
        "上海": "多云，28°C，湿度65%",
        "深圳": "阵雨，30°C，适合带伞",
    }
    return weather_data.get(city, f"抱歉，暂未收录 {city} 的天气数据")

# 创建一个带工具的天气查询 Agent
weather_agent = Agent(
    name="weatherbot",
    description="天气查询助手",
    system_prompt="你是一个天气查询助手。使用工具查询用户指定城市的天气。",
    tools=[get_weather],  # 将工具注册给 Agent
)

# 测试查询
result = weather_agent.run("北京今天天气怎么样？")
print(result)
```

运行：

```bash
python weather_agent.py
```

预期输出：

```
北京今天天气：晴，25°C，空气质量良。适合户外活动，记得做好防晒哦！
```

**关键概念**：`tools` 参数接受一个函数列表。每个函数的 **docstring + 参数注解** 会被自动解析为工具描述，Agent 会在需要时自主决定调用哪个工具。

---

## 第三步：连接多个 Agent — AgentMesh 雏形

AgentMesh 的核心价值：让多个 Agent 协作完成一个任务。

创建一个文件 `multi_agent.py`：

```python
from agentmesh import Agent, Mesh

# Agent 1：搜索专家
search_agent = Agent(
    name="searcher",
    description="信息搜索专家",
    system_prompt="你负责从给定信息中提取关键事实和数据。",
)

# Agent 2：写作专家
writer_agent = Agent(
    name="writer",
    description="内容写作专家",
    system_prompt="你负责将关键信息组织成流畅、易读的文章。",
)

# Agent 3：审查专家
reviewer_agent = Agent(
    name="reviewer",
    description="质量审查专家",
    system_prompt="你负责检查内容的准确性、完整性和可读性，指出需要改进的地方。",
)

# 组建 AgentMesh
mesh = Mesh()

# 注册 Agent 到 Mesh
mesh.register(search_agent)
mesh.register(writer_agent)
mesh.register(reviewer_agent)

# 定义协作任务
task = """
请完成以下工作流：
1. searcher：搜索关于 Python 异步编程的 3 个核心概念
2. writer：基于 searcher 的结果，写一篇 200 字左右的简介
3. reviewer：审查 writer 的产出，给出改进建议
"""

# 执行多 Agent 协作
result = mesh.run(task)
print("最终产出:", result)
```

运行：

```bash
python multi_agent.py
```

预期流程：

1. `searcher` 提取 Python 异步编程的 3 个核心概念（如 async/await、事件循环、协程）
2. `writer` 基于结果撰写简介
3. `reviewer` 审查并提出改进建议

---

## 第四步：A2A 协议通信 — 跨进程 Agent 协作

AgentMesh 的 A2A (Agent-to-Agent) 协议允许 Agent 跨进程、跨机器通信。

### 启动 A2A Server

创建 `server.py`：

```python
from agentmesh import Agent, A2AServer

# 定义一个可供外部调用的 Agent
compute_agent = Agent(
    name="compute",
    description="计算服务 Agent",
    system_prompt="你是一个计算专家，擅长数学运算和数据分析。",
    tools=[
        lambda x, y: x + y,
        lambda x, y: x * y,
    ],
)

# 启动 A2A Server，监听 8080 端口
server = A2AServer(agent=compute_agent, host="127.0.0.1", port=8080)
server.start()
```

### 调用 A2A Server

创建 `client.py`：

```python
from agentmesh import A2AClient, Agent

# 连接到 A2A Server
client = A2AClient(server_url="http://127.0.0.1:8080")

# 通过 A2A 协议发送请求
response = client.send("计算 127 + 256 的结果")
print("远程计算结果:", response)

# 也可以将一个本地 Agent 与远程 Agent 协作
local_agent = Agent(
    name="orchestrator",
    description="任务编排 Agent",
    system_prompt="你负责将任务分发给远程计算 Agent。",
    a2a_clients=[client],  # 注册远程连接
)

result = local_agent.run("请计算 (3 + 5) * 7 的值")
print("协作计算结果:", result)
```

---

## 完整示例：智能客服助理

将上述知识点整合为一个完整的智能客服助理。

创建 `customer_service.py`：

```python
from agentmesh import Agent, Mesh

# 工具：订单查询
def query_order(order_id: str) -> dict:
    """查询订单状态。

    Args:
        order_id: 订单编号

    Returns:
        订单信息字典
    """
    return {
        "order_id": order_id,
        "status": "已发货",
        "estimated_delivery": "2026-06-05",
        "items": ["无线蓝牙耳机 x1"],
    }

# 工具：退换货处理
def return_request(order_id: str, reason: str) -> str:
    """提交退换货申请。

    Args:
        order_id: 订单编号
        reason: 退换原因

    Returns:
        申请结果
    """
    return f"退换货申请已提交（订单: {order_id}），客服将在24小时内联系您。原因: {reason}"

# 客服 Agent
cs_agent = Agent(
    name="customer_service",
    description="智能客服助理",
    system_prompt="""你是一个专业的电商客服助理。你的职责：
1. 热情礼貌地接待顾客
2. 使用工具查询订单状态
3. 协助处理退换货
4. 如果问题无法解决，转接人工客服""",
    tools=[query_order, return_request],
)

# 质检 Agent（监督客服质量）
qa_agent = Agent(
    name="qa_reviewer",
    description="客服质量审查员",
    system_prompt="你负责审查客服对话质量，确保回答准确、礼貌、完整。",
)

# 组建客服 Mesh
support_mesh = Mesh()
support_mesh.register(cs_agent)
support_mesh.register(qa_agent)

# 模拟客户对话
dialogue = [
    "你好，我想查一下我的订单，订单号是 ORD-20260601",
    "我想申请退货，因为耳机有杂音",
]

for msg in dialogue:
    response = cs_agent.run(msg)
    print(f"顾客: {msg}")
    print(f"客服: {response}")
    print()
```

---

## 下一步

| 方向 | 说明 | 链接 |
|------|------|------|
| 深入概念 | 了解 Providers / Runtime / Adapter 架构 | [概念文档](../concepts/providers.md) |
| API 参考 | 查看所有公开 API 详细签名 | [API 文档](../api-reference/index.md) |
| 运行示例 | 本地运行更复杂的多 Agent 示例 | [示例库](../examples/04-local-bridge.md) |
| 故障排查 | 遇到问题？查看常见问题与解决方案 | [故障排查](../troubleshooting.md) |

---

## 排错指南

### pip install 失败

```bash
# 确保 pip 版本最新
pip install --upgrade pip

# 如果依赖冲突，使用虚拟环境
python -m venv fresh_env
source fresh_env/bin/activate
pip install agentmesh
```

### 运行时 ImportError

确保安装的是最新版本：

```bash
pip install --upgrade agentmesh
python -c "import agentmesh; print(agentmesh.__version__)"
```

### A2A 连接拒绝

确认 A2A Server 已启动：

```bash
# 检查端口是否在监听
curl http://127.0.0.1:8080/health
# 或
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read())"
```

---

> 本文档是 AgentMesh 教程系列的第一篇。后续教程预告：
>
> - **教程2**：自定义 Provider — 对接你的 LLM
> - **教程3**：构建多 Agent 工作流 — 任务编排实战
> - **教程4**：生产部署 — Docker + Kubernetes
