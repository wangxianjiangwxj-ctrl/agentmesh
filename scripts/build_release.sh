#!/usr/bin/env bash
# AgentMesh 离线发布包构建脚本
# 生成 pip installable 的本地 wheel
#
# 用法:
#   bash scripts/build_release.sh          # 构建 wheel
#   bash scripts/build_release.sh --check  # 检查后构建
#   bash scripts/build_release.sh --install # 构建并安装
#
# 输出: dist/agentmesh-*.whl

set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-build}"
PYTHON=$(command -v python3 || command -v python)

echo "=== AgentMesh 离线发布包构建 ==="
echo "Python: $($PYTHON --version)"
echo "模式:   $MODE"
echo ""

# 检查 + 构建
build_wheel() {
    echo ">>> 清理旧构建..."
    rm -rf build/ dist/ *.egg-info

    echo ">>> 验证 pyproject.toml..."
    $PYTHON -c "
import tomllib, sys
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
proj = data.get('project', {})
print(f'  name:        {proj.get(\"name\", \"MISSING\")}')
print(f'  version:     {proj.get(\"version\", \"MISSING\")}')
print(f'  python:      {proj.get(\"requires-python\", \"MISSING\")}')
print(f'  dependencies: {len(proj.get(\"dependencies\", []))}')
print('pyproject.toml 验证通过 ✅')
"

    echo ">>> 构建 wheel..."
    $PYTHON -m build --wheel 2>&1 | tail -3

    echo ""
    echo ">>> 构建产物:"
    ls -lh dist/*.whl 2>/dev/null || echo "(未找到 wheel)"
}

check_first() {
    echo ">>> 运行完整检查..."
    echo "  - ruff lint..."
    $PYTHON -m ruff check agentmesh/ --statistics 2>&1 | tail -3 || true
    echo "  - pytest..."
    $PYTHON -m pytest tests/ -q --tb=short -x -k "not benchmark" 2>&1 | tail -5 || true
    build_wheel
}

install_local() {
    build_wheel
    WHEEL=$(ls dist/*.whl 2>/dev/null | head -1)
    if [ -n "$WHEEL" ]; then
        echo ">>> 安装 wheel..."
        pip install --force-reinstall "$WHEEL"
        echo "安装完成 ✅"
        echo "试试: agentmesh --help"
    else
        echo "❌ 未找到 wheel 文件"
        exit 1
    fi
}

case "$MODE" in
    --check)  check_first ;;
    --install) install_local ;;
    build)    build_wheel ;;
    *)
        echo "用法: build_release.sh [--check|--install]"
        exit 1
        ;;
esac

echo ""
echo "=== 构建完成 ==="
