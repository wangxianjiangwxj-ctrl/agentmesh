# 贡献指南

## 本地开发环境

### 前置要求

- Python >= 3.10
- pip >= 21

### 安装

```bash
# 克隆仓库后，进入项目目录
cd agentmesh

# 安装开发依赖
pip install -e ".[dev]"

# 安装 pre-commit hooks（可选）
pre-commit install
```

### 验证安装

```bash
# 运行 lint
ruff check .

# 运行测试
make test

# 生成健康报告
make health
```

## 开发工作流

### 1. 分支

- `main` — 稳定版，随时可发布
- `dev/<feature>` — 功能开发分支
- `fix/<bug>` — 修复分支

### 2. 代码风格

遵循 PEP 8 和 Google Python Style Guide。使用 ruff 自动检查。

```bash
# 检查 lint
ruff check .

# 自动格式化
ruff format .
```

类型注解规则：
- 所有 public API 必须有类型注解（ANN 规则）
- 所有 public 函数/方法必须有 docstring（Google 风格）
- 模块级变量必须有类型注解

### 3. 测试

```bash
# 运行所有测试（跳过 benchmarks）
make test

# 仅 platform 测试
make test-platform

# 运行单个测试文件
python -m pytest tests/platform/test_escrow.py -v
```

测试要求：
- 新增功能必须有配套测试（覆盖率 >= 85%）
- 修复 bug 必须先加复现测试
- 运行 `make test` 全部通过才能提交

### 4. Docstrings

使用 Google 风格：

```python
def function_name(param1: str, param2: int) -> bool:
    """简短描述。

    Args:
        param1: 参数描述。
        param2: 参数描述。

    Returns:
        返回值描述。

    Raises:
        ValueError: 什么时候抛出。
    """
```

### 5. 提交 PR

1. 确保 `make test` 和 `ruff check .` 通过
2. `make health` 评分不低于 80/100
3. 更新 CHANGELOG.md（Phase 编号 + 变更摘要）
4. 提交 PR，描述变更内容和动机

## 项目结构

```
agentmesh/
├── agentmesh/              # 核心 SDK
│   ├── __init__.py         # SDK 入口
│   ├── a2a/                # A2A 协议实现
│   ├── a2a_models.py       # A2A 数据模型
│   ├── a2a_provider.py     # A2A 提供者接口
│   ├── a2a_server.py       # A2A HTTP 服务器
│   └── platform/           # AgentMesh 平台
│       ├── identity/       # 身份管理
│       ├── escrow.py       # 托管合约
│       ├── audit_chain.py  # 审计链
│       ├── reputation.py   # 声誉管理
│       ├── evidence_chain.py  # 证据链
│       ├── task_market_api.py # 任务市场 API
│       └── db_schema.py    # 数据库 Schema
├── tests/                  # 测试
│   ├── platform/           # 平台模块测试
│   ├── gateway/            # 网关测试
│   └── e2e/                # 端到端测试
├── docs/                   # 文档
├── examples/               # 示例代码
├── demo/                   # 一键 Demo
├── scripts/                # 工具脚本
├── pyproject.toml          # 项目配置
├── Makefile                # 常用命令
└── CONTRIBUTING.md         # 本文件
```

## 发布流程

```bash
# 1. 确认 main 分支通过所有测试
make test && ruff check . && make health

# 2. 更新版本号
# 编辑 pyproject.toml 中的 version 字段

# 3. 构建发布包
python -m build
# 输出: dist/agentmesh-<version>.tar.gz
#       dist/agentmesh-<version>-py3-none-any.whl

# 4. 本地验证 wheel
pip install dist/agentmesh-<version>-py3-none-any.whl
python -c "import agentmesh; print(agentmesh.__version__)"

# 5. 更新 CHANGELOG.md
# 6. 创建 GitHub Release 标签
```

## 常见问题

### 网络不通

Mac mini 开发机没有出站网络。离线开发：

```bash
# 安装依赖使用本地 wheel（需提前在有网络的机器上打包）
pip install dist/agentmesh-<version>-py3-none-any.whl

# 或者使用已缓存的依赖
pip install --no-index --find-links=./wheels -r requirements.txt
```

### 测试失败

```bash
# 检查是否缺少依赖
pip list | grep -E "pytest|fastapi|uvicorn"

# 检查数据库 Schema 变更
git diff db_schema.py

# 查看详细错误
make test 2>&1 | tail -50
```
