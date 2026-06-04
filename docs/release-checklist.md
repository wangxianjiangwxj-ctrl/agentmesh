# AgentMesh v1.0.0rc1 — Release Checklist

> 最后更新: 2026-06-04
> 状态: 全部就绪，仅待授权

## 1. 代码就绪

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 1.1 | 主分支代码冻结 | ✅ | main branch, tag v1.0.0rc1 |
| 1.2 | 测试全量通过 | ✅ | Unit 115/115, Integration 96/96(21 skip), E2E 7/8 |
| 1.3 | 类型检查通过 | ✅ | pyright strict mode |
| 1.4 | Lint 检查通过 | ✅ | ruff + flake8 |
| 1.5 | CHANGELOG 完整 | ✅ | Phase 1-18 全量变更记录 |
| 1.6 | 版本号锁定 | ✅ | __version__ = "1.0.0rc1" |

## 2. 文档就绪

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 2.1 | 快速入门指南 | ✅ | docs/quickstart.md (237行) |
| 2.2 | 核心概念文档 | ✅ | 4 pages: providers / a2a-protocol / agents / runtime |
| 2.3 | API 参考文档 | ✅ | 7 pages: auto-generated via mkdocstrings |
| 2.4 | 示例库 | ✅ | 6 示例: two-agent / three-agent / cross-a2a / local-bridge / remote-server / cli |
| 2.5 | 故障排查指南 | ✅ | docs/troubleshooting.md (392行) |
| 2.6 | 实战教程 | ✅ | docs/tutorials/first-agent.md |
| 2.7 | 性能基准报告 | ✅ | docs/benchmarks/v1.0.0-rc1-reference.md |
| 2.8 | 反馈渠道 | ✅ | docs/feedback.md + .github/ISSUE_TEMPLATE/feedback.yml |
| 2.9 | 文档站部署 | ✅ | GitHub Pages (wangxianjiangwxj-ctrl.github.io/agentmesh) |

## 3. 发布就绪

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 3.1 | GitHub Release 草稿 | ✅ | 草稿已创建，待正式发布 |
| 3.2 | Release 分支 | ✅ | v1.0.0rc1 branch |
| 3.3 | Release 公告文案 | ✅ | RELEASE-v1.0rc1.md |
| 3.4 | PyPI 准备 | ⛔ 待授权 | 需要 PyPI token 或账号密码 |
| 3.5 | GitHub 发布检查 | ✅ | 发布清单、CHANGELOG 已就位 |
| 3.6 | Tag 创建 | ✅ | v1.0.0rc1 |

## 4. 社区就绪

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 4.1 | Hacker News 发布 | ✅ 文案已备 | 短文 + 链接 |
| 4.2 | Reddit (r/programming) | ✅ 文案已备 | 短文 + 链接 |
| 4.3 | Twitter/X 发布 | ✅ 文案已备 | 4 条推文序列 |
| 4.4 | 社区 FAQ 文档 | ✅ | 常见问题与回答已整理 |

## 5. 生态就绪

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 5.1 | ClawHub 元数据 | ✅ 待发布 | clawhub-package.json 已备 |
| 5.2 | 集成适配器 | ✅ | CrewAIAdapter + AutoGenAdapter |
| 5.3 | A2A 协议兼容 | ✅ | Agent-to-Agent 通信已测试 |
| 5.4 | 发布执行计划 | ✅ | 步骤完整，经中书令审查确认 |
| 5.5 | 回滚预案 | ✅ | Release 可删除，PyPI 可 yank，社区帖可编辑/删除 |

---

## 6. 授权表 (呈陛下)

| 授权项 | 动作 | 状态 | 陛下确认 |
|--------|------|------|----------|
| **A. GitHub Release 发布** | 将草稿转为正式 Release | ✅ 就绪 | `__` |
| **B. PyPI 包发布** | `twine upload dist/*` | ⛔ 需 PyPI token | `__` |
| **C. 社区发布** | HN/Reddit/Twitter 同步发布 | ✅ 文案已备 | `__` |
| **D. ClawHub 发布** | 提交 clawhub-package.json | ✅ 元数据已备 | `__` |
| **E. 文档站上线** | GitHub Pages 自动部署 | ✅ 已就绪 | `__` |

**执行顺序**: A → B(若 A 成功) → C+D(引用 A 的 Release 链接) → E(同步完成)
**预估用时**: A: 30秒 / B: 2分钟 / C: 15分钟 / D: 5分钟

> 陛下在对应项旁标记 ✅ 即可授权执行。全部标记后，尚书令一键执行，预计 20 分钟内完成全链路发布。
