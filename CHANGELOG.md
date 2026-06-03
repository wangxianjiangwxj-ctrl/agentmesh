# CHANGELOG

## v1.0.0rc1 (2026-06-03)

Release Candidate 1 — 首个正式发布候选版。

### 新增 (Phase 1-7: 核心骨架)
- **A2A 协议适配器基类** (`a2a_adapter`): Provider-agnostic agent-to-agent communication
- **数据模型** (`a2a_models`): AgentCard, Task, Message, Artifact, A2ARequest, A2AResponse
- **传输层 Provider** (`a2a_provider`): HttpProvider, SSEProvider, MemoryProvider
- **CLI 工具** (`agentmesh serve` / `agentmesh connect`): 启动 A2A Server 与客户端连接
- **状态管理**: A2ATaskManager + A2ATaskState 状态机（pending→working→completed/failed）

### 新增 (Phase 8-9: CI 与基础增强)
- GitHub Actions CI/CD: lint, typecheck, test on 3.10/3.11/3.12
- A2A Server 异常处理 + 超时重试
- SDK 模块化重构

### 新增 (Phase 10: 发布准备)
- **A2A HTTP Server**: 可运行 demo server
- **英文博客**: 介绍 A2A 协议与 AgentMesh
- **GitHub Pages 文档站**: 自动部署
- **ClawHub 元数据**: 待发布

### 新增 (Phase 11: SDK v0.3)
- CI v2: 并行 job + 缓存 + test-sdk job
- SDK v0.3: a2a_provider.py 345 行, 6 测试
- 文档: QuickStart + FAQ + CHANGELOG + README 更新
- CLI 强化: `serve` + `connect` 命令 1570 行
- 示例: 本地 3 脚本 + a2a-bridge + CrewAI

### 新增 (Phase 12: 测试矩阵)
- **示例合并 PR #1**: 20 文件 / 2640 行, 4 子目录
- **单元测试**: 36 个 (MemoryProvider/TaskManager/Facade/Protocol/StateMachine)
- **集成测试 Layer 2**: 42 个通过 (仅 stdlib 零外部依赖)
- **社区发布文案**: HN/Reddit/Twitter/AGENTS.md 全部就绪

### 新增 (Phase 13: 包路径迁移 + 可观测性 + 适配器)
- 包路径重构: `sdk/` → 顶层 `agentmesh/` 包
- **可观测性**: 71/71 测试通过
- **CrewAIAdapter**: 1248 行, 45 methods
- **AutoGenAdapter**: 1554 行, 16 methods
- 总测试: Unit 115/115 / Integration 96/96(21 skip) / E2E 7/8

### 新增 (Phase 14: 真实集成 + 文档站)
- **A2A Test Server**: 6 E2E 测试, 4 种场景
- **SSE 异常路径测试**: 15/15 通过
- **多轮会话测试**: 6/6 通过
- **RealIntegrationTestRunner**: 31/31 + adapter 10 tests
- **文档站升级 PR #4**: mkdocs-material 主题 + mkdocstrings + CI/CD
- 总测试: 106 passed / 17 skipped / 0 failed

### 新增 (Phase 15: 代码质量)
- P0a 日志系统增强
- P0b 异常处理增强 (19 tests)
- P0c 健康检查端点 (16 tests)
- P0d 超时与重试 (37 tests)
- P1a linter 配置 (ruff.toml)
- P1b 类型注解 (3 files + strict)
- P1c 文档增强 (8 files: quickstart + API + test-server guide)
- P1d CI/CD 增强

### 新增 (Phase 16: 文档站深度增强)
- P0: mkdocs-material 主题配置 + 双配色 + logo + API 自动生成 + GitHub Pages CI
- P1: 核心概念文档 4 页 (providers/a2a-protocol/agents/runtime) + 故障排查指南 392 行 + 示例库 6 示例
- P2: navigation.indexes + search.share + font + social links + SEO 元数据

### 新增 (Phase 17: 发布冲刺)
- **A** 实战教程: "从零搭建第一个 Agent" 落地 mkdocs
- **B** 发布检查清单: RELEASE-v1.0rc1.md
- **C** 社区 FAQ: 常见问题汇总
- **版本号**: v1.0.0rc1

### 变更
- SDK 结构: 从 flat module 重构为 package 结构 (agentmesh/)
- CI: 适配 agentmesh/ 包结构, CI v2 trunk-based workflow
- 测试框架: 从手动 testing 迁移到 pytest + conftest 共享 fixture
- 文档: 从纯 README → mkdocs 文档站 15+ 页面

### 修复
- CI publish_dir 与 mkdocs build 路径问题
- SDK test 路径适配 ruff/mypy
- GitHub Pages 未配置 gh-pages 分支
- 代理网络限制导致 git push 偶发失败

### 测试覆盖 (v1.0.0rc1 基线)

| 层次 | 通过 | 跳过 | 通过率 |
|------|------|------|--------|
| 单元测试 | 115 | 0 | 100% |
| 集成测试 | 96 | 21 | 100% (含 SSE 占位) |
| E2E 测试 | 106 | 17 | 100% |
| **总计** | **317** | **38** | **100%** |

---

## v0.3.0 (2026-05-28)

### Added
- A2A Provider abstraction layer (A2AProvider, MemoryProvider, HttpProvider)
- A2A Task Manager with state machine (A2ATaskManager, A2ATaskState)
- A2A Facade unified entry point (A2AFacade)
- A2A Result and Error handling (A2AResult, A2AError)
- GitHub Actions CI/CD (lint, typecheck, test on 3.10/3.11/3.12, docs deploy)
- A2A bridge examples (MemoryProvider + HTTP Server)
- LangGraph integration example
- CrewAI integration example
- English blog post

### Changed
- SDK restructuring: modular provider/adapter/task layers
- CI: trunk-based workflow (main + feature/*)

### Fixed
- CI publish_dir and mkdocs build paths
- SDK test paths for ruff and mypy

---

## v0.2.0 (2026-05-20)

### Added
- A2A protocol message model definitions
- CLI tool entry point (`agentmesh`)
- Basic HTTP server implementation
- Memory-based A2A provider

### Changed
- Project restructured to support SDK + CLI separation

## v0.1.0 (2026-05-15)

### Added
- Project scaffold: Python package structure, pyproject.toml
- Core A2A data models (AgentCard, Task, Message, Artifact)
- A2A Adapter base class
- README with project overview
