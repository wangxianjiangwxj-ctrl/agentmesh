# AgentMesh v1.0.0rc1 — Release Candidate

## 概述

AgentMesh v1.0.0 RC1 — 多 Agent 协作中间件，支持 A2A 协议适配 + CLI 工具 + Python SDK。

预计正式发布：2026-06-07

## 核心功能

- **A2A 协议适配**: Task-based agent-to-agent communication，支持 HTTP + SSE 传输
- **CLI 工具** (`agentmesh`):
  - `serve` — 启动 A2A Server
  - `connect` — 连接远程 A2A Server
  - 状态管理、心跳检测
- **Python SDK**:
  - `a2a_adapter`: A2A 协议适配器基类
  - `a2a_models`: 数据模型（AgentCard, Task, Message, Artifact 等）
  - `a2a_provider`: 传输层 Provider（HttpProvider 等）
- **集成适配器**: CrewAIAdapter, AutoGenAdapter
- **文档站**: https://wangxianjiangwxj-ctrl.github.io/agentmesh/

## 变更统计 (since initial release)

| 维度 | 数值 |
|------|------|
| 提交数 | 100+ |
| 代码行 | ~15,000+ |
| 单元测试 | 115/115 ✅ |
| 集成测试 | 96/96 (21 skip) ✅ |
| E2E 测试 | 106/106 (17 skip) ✅ |

## 测试覆盖

| 层次 | 通过 | 跳过 | 说明 |
|------|------|------|------|
| 单元测试 | 115 | 0 | SDK + CLI + adapters |
| 集成测试 | 96 | 21 | Memory/TaskManager/Facade/Protocol/StateMachine |
| E2E 测试 | 106 | 17 | A2A Server SSE/多轮/真实集成场景 |

## 安装方式

```bash
pip install agentmesh
```

或从源码安装：

```bash
git clone https://github.com/wangxianjiangwxj-ctrl/agentmesh.git
cd agentmesh
pip install -e .
```

## 已知问题

1. ClawHub 发布等待授权
2. 社区发布（HN/Reddit/Twitter）等待授权
3. 国内容器 GitHub push 偶发网络限制

## 下一步

| 方向 | 优先级 | 负责人 | 状态 |
|------|--------|--------|------|
| 真实集成测试增强 | P1 | 尚书令+中书令 | ✅ Phase 14 |
| 文档站深度增强 | P2 | 尚书令 | ✅ Phase 16 |
| 社区运营发布 | P3 | 中书令+尚书令 | ⛔ 等授权 |
| ClawHub 发布 | P3 | 尚书令 | ⛔ 等授权 |
