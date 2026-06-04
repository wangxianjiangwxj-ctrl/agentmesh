# AgentMesh v1.0.0 发布检查清单

> 最后更新: 2026-06-04 12:00

## 一、代码质量 (Code Quality)

- [ ] 所有 Phase 1-18 代码已合并到 main 分支
- [ ] CI 流水线通过 (lint / typecheck / test / coverage)
- [ ] 单元测试全部通过
- [ ] 集成测试全部通过
- [ ] 端到端测试全部通过
- [ ] 性能基准测试 >= 参考线 (docs/benchmarks/v1.0.0-rc1-reference.md)
- [ ] 无 P0/P1 级 Bug 未关闭
- [ ] CHANGELOG 完整覆盖 Phase 1-18

## 二、文档 (Documentation)

- [ ] 文档站已构建并通过 (mkdocs build --strict)
- [ ] 快速入门指南已验证可独立完成
- [ ] 核心概念文档完整 (A2A协议 / Agent / Provider / Runtime)
- [ ] API 参考自动生成通过 (mkdocstrings)
- [ ] 6个示例均可在本地环境运行
- [ ] 故障排查指南内容完整
- [ ] 实战教程已验证 (docs/tutorials/first-agent.md)
- [ ] FAQ / 社区文案已准备
- [ ] 架构文档已更新
- [ ] AGENTS.md 集成指南已更新

## 三、发布产物 (Release Artifacts)

### GitHub Release
- [ ] Release v1.0.0 草稿已创建
- [ ] Release 标题和正文完整
- [ ] 已关联正确 Tag (v1.0.0)
- [ ] 变更摘要清晰
- [ ] 升级指南包含破坏性变更说明
- [ ] 经陛下授权后发布

### PyPI 发布
- [ ] pyproject.toml 版本号已更新为 v1.0.0
- [ ] README / 长描述已适配 PyPI 渲染
- [ ] 构建产物测试通过 (python -m build)
- [ ] twine check 通过
- [ ] 经陛下授权 + PyPI token 后执行

### ClawHub 发布
- [ ] clawhub-package.json 元数据已就绪
- [ ] 包描述和标签已完善
- [ ] 经陛下授权后发布

## 四、社区分发 (Community Distribution)

- [ ] Reddit 文案已备 (r/MachineLearning / r/Python)
- [ ] Hacker News 文案已备
- [ ] Twitter/X 公告贴已备
- [ ] 技术博客已发布 (docs/blog/)
- [ ] 经陛下授权后发布

## 五、反馈基础设施 (Feedback Loop)

- [ ] feedback.md 已在线 (docs/feedback.md)
- [ ] GitHub Issue 模板已部署 (.github/ISSUE_TEMPLATE/feedback.yml)
- [ ] 反馈渠道可正常工作

## 六、发布后验证 (Post-Release Validation)

- [ ] 通过 pip install agentmesh 可正常安装
- [ ] 首个 Agent 可独立创建并运行
- [ ] 文档站可正常访问
- [ ] GitHub Release 页面显示正常
- [ ] 钉钉/微信群/论坛等渠道启动社区反馈收集

---

## 依赖的外部授权

| 项目 | 责任方 | 步骤数 | 备注 |
|------|--------|--------|------|
| GitHub Release 正式发布 | 陛下 | 1 | 草稿已就绪，审批后点"Publish" |
| PyPI 发布 | 陛下 | 3 | 需 PyPI token / 账号密码 |
| 社区发布 | 陛下 | 1 | 确认文案后可发布 |
| ClawHub 发布 | 陛下 | 1 | 元数据已备 |

## 无授权依赖项 (可先行完成)

- [x] CHANGELOG 修订 (Phase 12-18)
- [x] 发布检查清单编制 (本文档)
