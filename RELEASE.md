# AgentMesh 离线发布

## 概览

AgentMesh 离线发布包用于将完整代码迁移到有网络的机器上进行部署和运行。
本包不依赖网络构建，所有源码已包含在内。

## 快速开始

### 在目标机器上

```bash
# 1. 解压
tar xzf agentmesh-*.tar.gz
cd agentmesh-*

# 2. 安装运行时依赖（需要网络）
pip install -r requirements.txt

# 3. 验证 Python 版本
python --version  # 需要 3.10+

# 4. 启动 API 网关
cd platform-agentmesh
python -m gateway.main
# 监听 http://0.0.0.0:8000

# 5. 健康检查
curl -H "X-API-Key: test-key" http://localhost:8000/api/v1/health
```

### 源代码目录结构

```
agentmesh-<version>/
├── platform-agentmesh/       # 平台核心代码
│   ├── identity/             # Module 1: Agent 身份管理
│   ├── task_market_api.py    # Module 2: 任务市场 + 状态机
│   ├── evidence_chain.py     # Module 3: 证据链
│   ├── escrow.py             # Module 4: 积分托管
│   ├── reputation.py         # Module 5: 声誉系统
│   ├── db_schema.py          # 统一 DB schema
│   ├── gateway/              # API 网关 (FastAPI)
│   └── agents/               # Agent 桥接层
├── sdk/                      # A2A Protocol SDK
│   └── agentmesh/
│       ├── a2a/              # 分布式追踪 + 结构化日志
│       └── integration/      # AutoGen/CrewAI 适配器
├── scripts/                  # 启动 + 构建 + E2E 脚本
├── architecture.md           # 系统架构文档
├── requirements.txt          # Python 依赖清单
└── Makefile                  # 构建目标
```

## 运行测试

```bash
cd platform-agentmesh
python -m pytest tests/ -v

# E2E 演示
python -m agentmesh.tests.test_e2e_demo
```

## 系统要求

- Python 3.10+
- 操作系统: macOS / Linux / Windows (WSL)
- 磁盘: < 50MB
- 内存: ~100MB (运行时)
