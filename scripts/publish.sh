#!/usr/bin/env bash
# AgentMesh 一键发布脚本
# =======================
# 用法:
#   bash scripts/publish.sh --dry-run   # 预览模式（必看）
#   bash scripts/publish.sh             # 执行发布
#
# 条件: git push 可通、PyPI 可通、Docker 可选
# 安全: --dry-run 检查所有步骤，无 side effect

set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
VERSION="v1.0.0rc1"
PYTHON=$(command -v python3 || command -v python)

# ─── 颜色 ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ─── 解析参数 ─────────────────────────────────────────────────────
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    info "▶ 预览模式(--dry-run) — 仅检查，不执行任何实际发布操作"
else
    info "▶ 执行模式 — 将执行完整发布流程"
    echo ""
    echo -e "${YELLOW}⚠ 即将发布 AgentMesh ${VERSION} 至 GitHub + PyPI + Docker Hub${NC}"
    echo -e "${YELLOW}⚠ 确认继续？(y/N)${NC}"
    read -r confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        info "已取消"
        exit 0
    fi
fi

SUMMARY=""
SUMMARY_FAIL=0
DRY_MSG=""
if $DRY_RUN; then DRY_MSG=" [预览]"; fi

# ─── 辅助函数 ──────────────────────────────────────────────────────
check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        warn "$1 未安装 — 跳过相关步骤"
        return 1
    fi
    return 0
}

run_step() {
    local step="$1"; shift
    local desc="$1"; shift
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}${step}${NC} $desc$DRY_MSG"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if $DRY_RUN; then
        echo -e "  ${YELLOW}→ 命令:${NC} $*"
        return 0
    fi
    if "$@"; then
        ok "$desc"
    else
        err "$step 失败"
        SUMMARY_FAIL=1
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════
# Step 0 — 环境检查
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║       AgentMesh 发布脚本  ${VERSION}        ║"
echo "╚═══════════════════════════════════════════════════╝"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  目录: $PROJECT_ROOT"
echo "  模式: $($DRY_RUN && echo '预览(--dry-run)' || echo '执行')"
echo ""

run_step "S0" "环境检查" true \
&& info "Python: $($PYTHON --version 2>&1)" \
&& check_cmd git \
&& (check_cmd twine || true) \
&& (check_cmd docker || true) \
&& ok "环境就绪"

# ═══════════════════════════════════════════════════════════════════
# Step 1 — Git 状态检查
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S1${NC} Git 状态检查$DRY_MSG"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CURRENT_BRANCH=$(git branch --show-current)
COMMIT_HASH=$(git rev-parse --short HEAD)
uncommitted=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
info "分支: $CURRENT_BRANCH  |  当前 commit: $COMMIT_HASH"

if $DRY_RUN; then
    if [[ "$uncommitted" -gt 0 ]]; then
        warn "存在 $uncommitted 个未提交变更 — 建议先 commit"
    fi
    info "将执行: git push origin $CURRENT_BRANCH"
    info "将执行: git tag $VERSION && git push origin $VERSION"
elif [[ "$uncommitted" -gt 0 ]]; then
    warn "存在 $uncommitted 个未提交变更，继续前请确认"
    echo -e "${YELLOW}  继续发布？(y/N)${NC}"
    read -r confirm2
    if [[ "$confirm2" != "y" && "$confirm2" != "Y" ]]; then
        info "已取消"
        exit 0
    fi
fi

# ═══════════════════════════════════════════════════════════════════
# Step 2 — Git Push + Tag
# ═══════════════════════════════════════════════════════════════════
run_step "S2" "Git push (origin/$CURRENT_BRANCH)" \
    git push origin "$CURRENT_BRANCH"

run_step "S2b" "Git tag $VERSION" \
    git tag -f "$VERSION"

run_step "S2c" "Push tag $VERSION to origin" \
    git push origin "$VERSION" || true

# ═══════════════════════════════════════════════════════════════════
# Step 3 — Build Python Wheel
# ═══════════════════════════════════════════════════════════════════
if check_cmd build; then
    run_step "S3" "清理旧构建" \
        rm -rf build/ dist/ *.egg-info

    run_step "S3b" "验证 pyproject.toml" \
        $PYTHON -c "
import tomllib, sys
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
proj = data.get('project', {})
print(f'  name={proj.get(\"name\")} version={proj.get(\"version\")}')
print('pyproject.toml 验证通过 ✅')
"

    run_step "S3c" "构建 wheel" \
        $PYTHON -m build --wheel

    run_step "S3d" "验证 wheel 文件" \
        ls -lh dist/agentmesh-*.whl
else
    warn "build 模块未安装 — 跳过 wheel 构建"
fi

# ═══════════════════════════════════════════════════════════════════
# Step 4 — PyPI 上传 (twine)
# ═══════════════════════════════════════════════════════════════════
if check_cmd twine; then
    run_step "S4" "PyPI 上传 (twine upload)" \
        twine upload dist/agentmesh-*.whl
else
    warn "twine 未安装 — 跳过 PyPI 上传"
    if ! $DRY_RUN; then
        info "安装方法: pip install twine"
        info "手动上传: twine upload dist/agentmesh-*.whl"
    fi
fi

# ═══════════════════════════════════════════════════════════════════
# Step 5 — Docker 构建 + Push
# ═══════════════════════════════════════════════════════════════════
if check_cmd docker; then
    run_step "S5" "Docker 构建 (agentmesh:${VERSION})" \
        docker build -f scripts/Dockerfile -t agentmesh:"${VERSION}" -t agentmesh:latest .

    run_step "S5b" "Docker 标签 (ghcr 等)" \
        docker tag agentmesh:"${VERSION}" ghcr.io/wangxianjiangwxj-ctrl/agentmesh:"${VERSION}" && \
        docker tag agentmesh:latest ghcr.io/wangxianjiangwxj-ctrl/agentmesh:latest

    run_step "S5c" "Docker push (ghcr.io)" \
        docker push ghcr.io/wangxianjiangwxj-ctrl/agentmesh:"${VERSION}" && \
        docker push ghcr.io/wangxianjiangwxj-ctrl/agentmesh:latest
else
    warn "docker 未安装 — 跳过 Docker 构建"
fi

# ═══════════════════════════════════════════════════════════════════
# Step 6 — 生成 GitHub Release Notes
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}S6${NC} 生成 GitHub Release Notes$DRY_MSG"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

LATEST_CHANGELOG=$(grep -n "^## " CHANGELOG.md | head -5 | tail -1 | cut -d: -f1)
if [[ -z "$LATEST_CHANGELOG" ]]; then
    LATEST_CHANGELOG=1
fi

RELEASE_NOTES_FILE="scripts/RELEASE_NOTES_${VERSION}.md"
if $DRY_RUN; then
    info "输出位置: $RELEASE_NOTES_FILE"
    info "将生成 v${VERSION} 的 Release Notes"
    head -$((LATEST_CHANGELOG - 1)) CHANGELOG.md 2>/dev/null | head -30 || true
else
    cat > "$RELEASE_NOTES_FILE" <<EOF
# AgentMesh ${VERSION}

## 概述

AgentMesh — Agent间协作中间件。支持 A2A 协议适配、Agent Economy Platform、MCP 工具接入。

## 安装

\`\`\`bash
pip install agentmesh
\`\`\`

## 变更

$(head -$((LATEST_CHANGELOG - 1)) CHANGELOG.md 2>/dev/null || echo "(从 CHANGELOG.md 生成)")

---

完整 CHANGELOG: CHANGELOG.md
EOF
    ok "Release Notes 已生成: $RELEASE_NOTES_FILE"
    info "使用 gh CLI 创建 GitHub Release:"
    echo "  gh release create ${VERSION} --title '${VERSION}' -F ${RELEASE_NOTES_FILE} dist/agentmesh-*.whl"
fi

# ═══════════════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "╔═══════════════════════════════════════════════════╗"
if $DRY_RUN; then
    echo "║      🔍 预览完成 — 未执行任何实际操作           ║"
    echo "║      移除 --dry-run 后执行完整发布                ║"
else
    if [[ $SUMMARY_FAIL -eq 0 ]]; then
        echo "║      ✅ 发布完成！                                ║"
    else
        echo "║      ⚠ 部分步骤失败，请查看上方错误信息          ║"
    fi
fi
echo "╚═══════════════════════════════════════════════════╝"
echo ""
echo "  Git tag:     ${VERSION}"
echo "  Commit:      $(git rev-parse --short HEAD 2>/dev/null || echo '?')"
echo "  Branch:      $(git branch --show-current 2>/dev/null || echo '?')"
echo "  Wheel:       dist/agentmesh-*.whl"
echo "  Release:     $RELEASE_NOTES_FILE"
echo ""

if $DRY_RUN; then
    info "运行 'bash scripts/publish.sh' 执行实际发布"
else
    info "发布完毕"
fi
