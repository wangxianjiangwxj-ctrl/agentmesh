# AgentMesh v1.0.0rc1 — 统一发布执行计划

> 版本: v1.0 (2026-06-04)
> 审查人: 中书令 (已确认步骤完整性 ✅)
> 执行人: 尚书令

## 执行前提

- [ ] 陛下授权确认（授权表已就位）
- [ ] main 分支代码已推送至最新
- [ ] 本地网络连通 GitHub（已验证 ✅）

---

## Step 1: GitHub Release 发布 (预估: 30s)

**动作**:
1. 登录 GitHub → Release 草稿 → 检查内容和 Tag → Publish release
2. 产出: Release URL

**验证**: Release 页面可公开访问，Tag 匹配 v1.0.0rc1

---

## Step 2: PyPI 包发布 (预估: 2min)

**前提**: GitHub Release 发布成功

**动作**:
1. `python -m build` → 生成 dist/*.whl dist/*.tar.gz
2. `twine upload dist/*` → 需要 PyPI token (需陛下提供)

**回滚**: `pip yank agentmesh 1.0.0rc1`

**注意**: 若 PyPI token 不可用，可走 GitHub Releases 的 .whl 附件方案替代发布

---

## Step 3: 社区同步发布 (预估: 15min)

**前提**: GitHub Release URL 已产出

**动作**:

| 渠道 | 动作 | 文案来源 |
|------|------|---------|
| Hacker News | 新建 submission → 标题+URL | RELEASE-v1.0rc1.md |
| Reddit r/programming | 新建 post → 标题+正文+URL | RELEASE-v1.0rc1.md |
| Twitter/X | 发布推文序列 (4条) | RELEASE-v1.0rc1.md |

**回滚**: HN/Reddit 可编辑/删除，Twitter 可删除

---

## Step 4: ClawHub 发布 (预估: 5min)

**前提**: GitHub Release 发布成功

**动作**:
1. 提交 clawhub-package.json 到 ClawHub 市场
2. 验证可搜索/可安装

---

## Step 5: 文档站确认 (预估: 1min)

**动作**: 确认 GitHub Pages 自动部署完成
**URL**: https://wangxianjiangwxj-ctrl.github.io/agentmesh/

---

## 总用时预估

| 步骤 | 用时 | 依赖 |
|------|------|------|
| Step 1 | ~30s | 无 |
| Step 2 | ~2min | Step 1 |
| Step 3 | ~15min | Step 1 (产出的 URL) |
| Step 4 | ~5min | Step 1 |
| Step 5 | ~1min | 与 Step 1-4 并行 |
| **总计** | **~20min** | — |

## 风险与应对

| 风险 | 概率 | 应对 |
|------|------|------|
| PyPI 账号不可用 | 中 | 用 GitHub Releases 附件替代发布 .whl |
| 社区审核延迟 | 高 | 提前 1h 发布，预留审核缓冲 |
| Docker Hub 方案 | 低 | 推迟至 v1.0.0 正式版 |
