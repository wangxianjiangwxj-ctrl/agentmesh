# CLI 工具

`agentmesh` 命令行工具提供5个核心命令。

---

## 安装

CLI 随 SDK 一起安装：

```bash
pip install agentmesh-sdk
```

## 命令概览

| 命令 | 功能 | 使用频率 |
|------|------|----------|
| `init` | 初始化项目 | 一次 |
| `validate` | 验证消息Schema | 多次 |
| `convert` | A2A双向格式转换 | 按需 |
| `fidelity` | 独立保真度追踪 | 按需 |
| `run` | 端到端流程执行 | 多次 |

---

## agentmesh init

在当前目录初始化AgentMesh项目，生成模板文件。

```bash
# 默认初始化
agentmesh init

# 指定项目名称
agentmesh init --name my-project

# 指定输出目录
agentmesh init --output ./my-project
```

**生成的文件**：

```
my-project/
├── agentmesh.yaml        # 项目配置
├── agents.yaml           # Agent注册配置
├── flows/                # 工作流目录
│   └── example.yaml      # 示例工作流
└── messages/             # 消息存储目录
```

---

## agentmesh validate

验证消息的L1 Schema合规性。

```bash
# 验证单条消息
agentmesh validate message.json

# 批量验证
agentmesh validate messages/*.json

# 详细输出（显示具体问题）
agentmesh validate message.json --verbose

# 输出验证报告到文件
agentmesh validate message.json --output report.json
```

**验证内容**：

- 5个必填字段是否存在：schema_version, message_id, message_type, sender, timestamp
- 字段类型是否正确
- message_type是否在允许范围内
- timestamp是否符合ISO 8601格式

---

## agentmesh convert

AgentMesh ↔ A2A 双向格式转换。

```bash
# 正向转换：AgentMesh → A2A
agentmesh convert message.json --to a2a

# 反向转换：A2A → AgentMesh
agentmesh convert a2a_task.json --to agentmesh

# 输出到文件
agentmesh convert message.json --to a2a --output a2a_output.json

# 批量转换
agentmesh convert input/*.json --to a2a --output-dir ./converted/
```

**选项**：

| 选项 | 说明 |
|------|------|
| `--to` | 目标格式：`a2a` 或 `agentmesh` |
| `--output` | 输出文件路径 |
| `--output-dir` | 批量转换输出目录 |
| `--pretty` | 格式化JSON输出 |

---

## agentmesh fidelity

独立的保真度追踪工具。

```bash
# 从消息链文件计算保真度
agentmesh fidelity chain.json

# 自定义警告阈值
agentmesh fidelity chain.json --threshold 0.6

# 详细输出
agentmesh fidelity chain.json --verbose

# 步进分析
agentmesh fidelity chain.json --steps
```

**chain.json 格式**：

```json
{
    "steps": [
        {"from": "agent-a", "to": "agent-b", "fidelity": 0.9},
        {"from": "agent-b", "to": "coordinator", "fidelity": 0.65}
    ]
}
```

**输出示例**：

```
=== 保真度追踪报告 ===

步骤:
  1. agent-a → agent-b: 0.900
  2. agent-b → coordinator: 0.650

累积保真度: 0.585
警告: False (阈值: 0.500)

信息损失: 41.5%
```

---

## agentmesh run

运行端到端协作流程。

```bash
# 运行工作流文件
agentmesh run flow.json

# 运行并输出报告
agentmesh run flow.json --report report.json

# 详细日志
agentmesh run flow.json --verbose
```

**flow.json 格式**：

```json
{
    "name": "研究协作",
    "agents": ["scout-alpha", "forge-beta"],
    "steps": [
        {
            "type": "retrieval",
            "from": "scout-alpha",
            "to": "forge-beta",
            "summary": "检索AI Agent安全研究",
            "data": {"sources": 5},
            "confidence": 0.85,
            "fidelity": 0.9
        },
        {
            "type": "integration",
            "from": "forge-beta",
            "to": "coordinator",
            "summary": "整合报告",
            "data": {"key_findings": 4},
            "confidence": 0.78,
            "fidelity": 0.65
        }
    ]
}
```

**输出摘要示例**：

```
=== 流程执行报告 ===

项目: 研究协作
状态: 完成
冲突率: 0.0%
累积保真度: 0.585
贡献度: scout-alpha=0.5095, forge-beta=0.4905
消息数: 2
```

---

## 全局选项

| 选项 | 说明 |
|------|------|
| `--help` | 显示帮助 |
| `--version` | 显示版本号 |
| `--verbose` | 详细输出 |
| `--quiet` | 静默模式（仅输出JSON） |
| `--config` | 指定配置文件路径 |

---

## 示例

```bash
# 1. 初始化项目
agentmesh init --name my-research

# 2. 编辑工作流配置 my-research/flows/study.yaml

# 3. 运行工作流
agentmesh run my-research/flows/study.yaml --report result.json

# 4. 验证消息
agentmesh validate result.json

# 5. 转换为A2A格式
agentmesh convert result.json --to a2a
```
