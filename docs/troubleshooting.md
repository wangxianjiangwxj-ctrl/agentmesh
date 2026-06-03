# 故障排查 (Troubleshooting)

> 常见问题及解决方案

---

## 安装问题

### pip install 失败

**现象**：

```bash
pip install agentmesh
# ERROR: Could not find a version that satisfies the requirement agentmesh
```

**原因**：AgentMesh 尚未发布到 PyPI，需要通过 Git 仓库安装：

```bash
pip install git+https://github.com/wangxianjiangwxj-ctrl/agentmesh.git
```

**或者**：从本地源码安装：

```bash
git clone https://github.com/wangxianjiangwxj-ctrl/agentmesh.git
cd agentmesh
pip install -e .
```

### uvicorn / fastapi 不可用

**现象**：当尝试启动 A2A Server 时，提示 `ModuleNotFoundError: No module named 'uvicorn'`。

**原因**：`uvicorn` 和 `fastapi` 是 A2A Server 的可选依赖。安装时不会自动安装。

**解决方案**：

```bash
# 安装 Server 依赖
pip install uvicorn fastapi

# 或者通过 extras 安装
pip install agentmesh[server]
```

### pydantic 版本冲突

**现象**：`ImportError: cannot import name 'BaseModel' from 'pydantic'`

**原因**：项目依赖的 `pydantic` 版本太高或太低。

**解决方案**：

```bash
pip install "pydantic>=1.10.0,<3.0.0"
```

---

## 连接问题

### A2A Server 连不上

**现象**：

```python
client = HttpProvider("http://localhost:8080")
result = client.ping()
# 抛出 ConnectionError 或超时
```

**检查步骤**：

1. **确认 Server 是否运行**：

```bash
# 命令行检查
curl http://localhost:8080/ping

# 应该返回类似：
# {"success": true, "data": {"status": "ok", "provider": "http"}, "error": null, "task_state": null}

# 如果连接被拒绝，检查端口：
netstat -an | grep 8080
```

2. **确认端口未被占用**：

```bash
# 查看 8080 端口的使用情况
lsof -i :8080

# 如果端口被其他进程占用，换一个端口启动：
python -m agentmesh.a2a_server server --port 8081
```

3. **确认 Server 启动没有报错**：

```bash
# 详细查看启动日志
python -m agentmesh.a2a_server server --port 8080 2>&1
```

4. **确认客户端 URL 正确**：

```python
# 常见错误：漏了端口号
client = HttpProvider("http://localhost")  # 错误！默认端口不是 80
client = HttpProvider("http://localhost:8080")  # 正确
```

### SSE 流式连接失败

**现象**：SSE 流式订阅没有任何事件输出。

**可能原因及解决方案**：

```python
# 1. 任务 ID 不存在
stream = SSEStream("http://localhost:8080", "nonexistent_task")
for event, data in stream:
    print(event, data)
    # 输出: ('error', {'message': 'Task not found'})

# 2. 连接超时
stream = SSEStream(
    "http://localhost:8080",
    "task_001",
    timeout=5,  # 设置合适的超时时间
    heartbeat_timeout=15.0,
)

# 3. 防火墙/代理拦截
# 确认没有代理拦截 SSE 连接：
# curl -N http://localhost:8080/stream/task_001
```

---

## 测试问题

### 内置测试报错

**现象**：运行内置测试时报错。

```bash
python -m agentmesh.a2a_server test
```

**常见错误及解决方案**：

```python
# 1. 端口 8080 被占用
# 错误: [Errno 48] Address already in use
# 解决方案：杀掉占用进程或用不同的端口

# 2. Server 启动超时
# 错误: Connection refused
# 解决方案：增加等待时间或手动启动 Server

# 3. A2AError: 非法状态转换
# 可能原因：测试使用了错误的 task_id
```

```python
# 在测试前确认 Server 可用
from agentmesh.a2a_server import HttpProvider

client = HttpProvider("http://localhost:8080")
try:
    result = client.ping()
    print(f"Server 可达: {result.success}")
except Exception as e:
    print(f"Server 不可达: {e}")
```

### Provider 单元测试失败

**现象**：

```python
from agentmesh.a2a_provider import MemoryProvider

mem = MemoryProvider()
result = mem.get_task("nonexistent")
assert not result.success  # 期望失败，通过
assert result.error.code == 404  # 期望 404
```

如果上述测试失败，请确认：

```bash
# 1. 确认使用的是最新版本
git pull

# 2. 确认没有修改过 Provider 代码
```

---

## 常见 Q&A

### Q1: AgentMesh 和传统的消息队列有什么区别？

AgentMesh A2A 协议不是消息队列。传统消息队列（如 RabbitMQ、Kafka）提供发布/订阅模式和持久化存储，而 AgentMesh 关注的是：

- Agent 之间的结构化协作（状态机、保真度追踪）
- 标准化的消息 Scheme（L1 Schema）
- 可量化的信息传递质量（保真度指标）

**结合使用**：可以用 Kafka 做消息持久化，AgentMesh 做消息 Schema 验证和协作编排。

### Q2: 一个 A2A Server 可以支持多少个 Agent？

理论上无硬性限制。实际受限于：

- 内存：每个任务和 Agent Card 占用少量内存
- 并发：Server 基于 FastAPI + uvicorn，支持异步并发
- 网络：HttpProvider 的连接数和超时配置

**推荐**：单 Server 承载 50-100 个活跃 Agent。更大规模建议采用分布式多 Server 架构。

### Q3: Agent 之间的消息会丢失吗？

在默认配置下（MemoryProvider），消息保存在内存中，Server 重启会丢失。

**消息可靠性建议**：

- 生产环境：实现自定义 Provider，持化化到数据库
- 关键消息：使用 SSE 确认送达
- 超时重试：配置合适的 `RetryConfig`

### Q4: 如何检查消息的保真度？

```python
from agentmesh import CollaborationFlow

flow = CollaborationFlow("检查保真度", use_signing=False)
flow.register_agent("agent-a")
flow.register_agent("agent-b")

flow.step_retrieval("agent-a", "agent-b", "样本数据", {"n": 10})
flow.step_integration("agent-b", "coordinator", "分析结果", {"findings": 3})

report = flow.full_report()
print(f"累积保真度: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
print(f"信息损失: {(1 - flow.fidelity_tracker.cumulative_fidelity) * 100:.1f}%")
```

### Q5: 如何同时使用 CrewAI 和 AutoGen 的 Agent？

通过 AgentMesh 的跨框架桥接功能：

```python
from agentmesh.a2a.integration import CrewAIAdapter, AutoGenAdapter

# 连接两个适配器到同一个 A2A Server
crewai_adapter = CrewAIAdapter()
crewai_adapter.connect("http://localhost:8080")

autogen_adapter = AutoGenAdapter()
autogen_adapter.connect("http://localhost:8080")

# 创建 Agent
crewai_agent = crewai_adapter.create_agent(...)
autogen_agent = autogen_adapter.create_agent(...)

# 桥接
autogen_adapter.bridge_to_crewai("auto-agent", "crew-agent")

# 现在两个框架的 Agent 可以互相通信
```

### Q6: 如何监控 A2A Server 的运行状态？

使用内置的健康检查端点：

```bash
# 快速检查
curl http://localhost:8080/ping

# 详细状态
curl http://localhost:8080/health
```

```python
# 在监控脚本中使用
from agentmesh.a2a_server import HttpProvider

def monitor():
    client = HttpProvider("http://localhost:8080")
    start = time.time()
    try:
        result = client.ping()
        latency = (time.time() - start) * 1000
        return {
            "status": "healthy" if result.success else "degraded",
            "latency_ms": round(latency, 2),
        }
    except Exception as e:
        return {
            "status": "down",
            "error": str(e),
        }
```

### Q7: 如何编译文档站点？

```bash
# 安装文档依赖
pip install mkdocs mkdocs-material mkdocstrings[python] mkdocs-macros-plugin

# 本地预览
cd /path/to/agentmesh
mkdocs serve

# 构建静态站点
mkdocs build --strict

# 部署到 GitHub Pages
mkdocs gh-deploy
```

### Q8: Agent 名称可以使用什么字符？

Agent 名称（agent_id）建议遵守以下规范：

- 只使用小写字母、数字和连字符：`a-z`, `0-9`, `-`
- 以字母开头
- 长度不超过 64 个字符

合规示例：`scout-alpha`, `agent-001`, `data-collector-v2`

### Q9: 如何处理大规模 Agent 场景？

建议采用分层架构：

```
┌──────────────────────────────────────────────┐
│               AgentMesh 编排层                │
│                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Server A │  │ Server B │  │ Server C │   │
│  │ (Region1)│  │ (Region2)│  │ (Region3)│   │
│  └──────────┘  └──────────┘  └──────────┘   │
│                                               │
│  HttpProvider 双向连接，形成 Mesh               │
└──────────────────────────────────────────────┘
```

### Q10: 如何贡献代码？

1. Fork 仓库：https://github.com/wangxianjiangwxj-ctrl/agentmesh
2. 创建特性分支：`git checkout -b feature/my-feature`
3. 提交代码：`git commit -am 'Add my feature'`
4. 推送到分支：`git push origin feature/my-feature`
5. 创建 Pull Request

**开发环境设置**：

```bash
git clone https://github.com/wangxianjiangwxj-ctrl/agentmesh.git
cd agentmesh
pip install -e ".[dev]"
```

---

## 诊断速查表

| 现象 | 可能原因 | 检查方法 | 解决方案 |
|------|----------|----------|----------|
| 安装失败 | 未发布到 PyPI | `pip install agentmesh` 报错 | 用 Git 仓库安装 |
| Server 启动报错端口占用 | 端口已被使用 | `lsof -i :8080` | 换端口或 kill 占用进程 |
| 连接被拒绝 | Server 未启动 | `curl localhost:8080/ping` | 启动 Server |
| SSE 无响应 | 任务不存在 | `client.get_task(id)` 返回失败 | 确认 task_id |
| 消息丢失 | 使用 MemoryProvider | 检查 Provider 类型 | 实现持久化 Provider |
| 状态转换异常 | 非法状态路径 | 检查状态机逻辑 | 确认转换合法性 |
| 跨框架通信失败 | Agent 未注册 | `health_check().agents` | 注册 Agent 到同一 Server |
| 日志不输出 | 日志级别太高 | `StructuredLogger.configure(...)` | 调低日志级别 |
| 编译文档失败 | 缺少 mkdocs 插件 | 运行 build 检查报错 | 安装缺失插件 |

---

## 获取帮助

- GitHub Issues：https://github.com/wangxianjiangwxj-ctrl/agentmesh/issues
- 文档站点：https://wangxianjiangwxj-ctrl.github.io/agentmesh/
- Architecture 文档：[架构说明](architecture.md)
- 完整示例：[示例目录](examples/01-two-agent-research.md)
