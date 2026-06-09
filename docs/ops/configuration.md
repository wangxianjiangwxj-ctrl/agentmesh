# AgentMesh 配置参考

> 版本: v1.0.0rc1 | 更新日期: 2026-06-09

本文档记录 `.env.prod.example` 中所有环境变量的含义、默认值、示例及最佳实践。同时包含 CLI 参数和日志配置的说明。

---

## 1. 环境变量总览

所有配置通过环境变量注入, 按功能分为以下组:

| 分组 | 变量数 | 作用 |
|------|--------|------|
| 数据库 | 1 | SQLite 存储路径 |
| 日志 | 2 | 日志级别与文件路径 |
| 服务 | 3 | HTTP 监听地址、端口、Worker 数 |
| 安全 | 1 | 密钥 (必填) |
| 可选外部服务 | 2 | PostgreSQL / Sentry (预留) |

---

## 2. 数据库配置

### `AGENTMESH_DB_DIR`

| 属性 | 值 |
|------|------|
| 描述 | SQLite 数据库文件的存储目录。数据持久化到该目录下的 `agentmesh_platform.db` 文件。容器/进程需要对该目录有写入权限。 |
| 必填 | 否 |
| 默认值 | `/var/lib/agentmesh/data` |
| 示例 | `AGENTMESH_DB_DIR=/data/agentmesh` |
| 环境读取位置 | `scripts/docker-compose.prod.yml` 中的 `app` 和 `db-init` 服务 |
| 代码引用 | `agentmesh/db_schema.py:init_db()`, `agentmesh/gateway/deps.py:init_db()` |

**最佳实践**:
- Docker 部署时挂载持久化卷: `volumes: - agentmesh_data:/var/lib/agentmesh`
- 确保目录权限为 750, 属主为运行用户
- 如需切换数据库文件路径, 重启后自动创建新文件 (若不存在)

---

## 3. 日志配置

### `AGENTMESH_LOG_LEVEL`

| 属性 | 值 |
|------|------|
| 描述 | 日志输出级别。控制 stderr 和文件的日志粒度。 |
| 必填 | 否 |
| 默认值 | `info` |
| 可选值 | `debug`, `info`, `warning`, `error`, `critical` |
| 示例 | `AGENTMESH_LOG_LEVEL=debug` |
| 环境读取位置 | `agentmesh/platform/logging_config.py:setup_logging()` |

**最佳实践**:
- 生产环境: `info` (提供足够信息, 避免 debug 级别的日志噪音)
- 调试/排障: `debug` (输出详细 SQL 执行、请求上下文等)
- 高负载场景: `warning` 或 `error` (减少日志 I/O)

### `AGENTMESH_LOG_DIR`

| 属性 | 值 |
|------|------|
| 描述 | JSON 结构化日志文件的输出目录。使用 `RotatingFileHandler`, 10 MB 每文件, 保留 5 个备份。当目录不可写时, 仅输出到 stderr。 |
| 必填 | 否 |
| 默认值 | `/var/lib/agentmesh/logs` |
| 示例 | `AGENTMESH_LOG_DIR=/var/log/agentmesh` |
| 环境读取位置 | `agentmesh/platform/logging_config.py:setup_logging()` |

**日志文件结构**:

```
/var/lib/agentmesh/logs/
├── agentmesh.log           # 当前日志
├── agentmesh.log.1         # 轮转 #1
├── agentmesh.log.2         # 轮转 #2
├── agentmesh.log.3         # 轮转 #3
├── agentmesh.log.4         # 轮转 #4
└── agentmesh.log.5         # 轮转 #5
```

**JSON 日志样例**:

```json
{"timestamp": "2026-06-09T14:30:00+00:00", "level": "INFO", "logger": "agentmesh", "module": "logging_config", "function": "setup_logging", "line": 105, "message": "Logging configured", "extra": {"level": "info", "log_dir": "/var/lib/agentmesh/logs"}}
```

**最佳实践**:
- Docker 场景: 将日志目录挂载到持久化卷, 或使用 Docker 的 json-file 日志驱动 (已配置)
- 高日志量场景: 调整轮转参数 (修改 `logging_config.py` 中的 `maxBytes` 和 `backupCount`)
- 日志聚合: JSON 格式天然适配 Loki / ELK / Datadog

---

## 4. 服务配置

### `AGENTMESH_HOST`

| 属性 | 值 |
|------|------|
| 描述 | HTTP 服务器的绑定地址。Docker 场景下必须为 `0.0.0.0` 以监听所有网络接口。 |
| 必填 | 否 |
| 默认值 | `0.0.0.0` |
| 示例 | `AGENTMESH_HOST=127.0.0.1` (仅本地访问) |
| 环境读取位置 | `scripts/docker-compose.prod.yml` 中的 `app` 服务环境变量 |
| CLI 参数 | `agentmesh serve --host <HOST>` |

**最佳实践**:
- Docker 部署: 使用默认 `0.0.0.0`
- 本地开发: 使用 `127.0.0.1` 避免外部访问
- 生产场景: 前方应配置反向代理 (Nginx / Caddy) 处理 TLS

### `AGENTMESH_PORT`

| 属性 | 值 |
|------|------|
| 描述 | HTTP 服务监听的端口号。需要与 Docker 的端口映射一致。 |
| 必填 | 否 |
| 默认值 | `8000` |
| 示例 | `AGENTMESH_PORT=8080` |
| 环境读取位置 | `scripts/docker-compose.prod.yml` 中的端口映射和 `app` 服务环境变量 |
| CLI 参数 | `agentmesh serve --port <PORT>` |

**Docker 端口映射**:

Compose 中端口映射为 `${AGENTMESH_PORT:-8000}:8000`, 即:
- 左侧(宿主机): 使用 `AGENTMESH_PORT` 的值 (默认 8000)
- 右侧(容器内): 固定 8000 (应用实际监听的端口)

如果宿主机端口被占用, 只需修改 `AGENTMESH_PORT`:

```bash
export AGENTMESH_PORT=8080
docker compose -f scripts/docker-compose.prod.yml up -d
# 访问: http://localhost:8080/api/v1/health
```

### `AGENTMESH_WORKERS`

| 属性 | 值 |
|------|------|
| 描述 | uvicorn Worker 进程数。多 Worker 利用多核 CPU 提升并发处理能力。 |
| 必填 | 否 |
| 默认值 | `4` |
| 示例 | `AGENTMESH_WORKERS=2` (1 核机器) |
| 环境读取位置 | `scripts/docker-compose.prod.yml` 中的 `app` 服务环境变量 |

**选值建议**:

| 场景 | CPU 核数 | 建议 Workers | 说明 |
|------|----------|--------------|------|
| 最小 | 1 | 1-2 | 开发/测试 |
| 标准 | 2 | 2-4 | 小型生产 |
| 推荐 | 4 | 4 | 中型生产 |
| 高性能 | 8+ | 4-8 | 大型部署, SQLite 为瓶颈时不宜过多 |

**注意事项**:
- SQLite 在高并发写入场景下可能成为瓶颈, Worker 数超过 4 不一定带来线性提升
- 每个 Worker 独立占用内存, 512 MB 内存建议不超过 4 Workers
- 调试排障时使用 `1`, 避免日志交错

---

## 5. 安全配置

### `AGENTMESH_SECRET_KEY`

| 属性 | 值 |
|------|------|
| 描述 | 会话签名、Token 加密的密钥。用于 AuthMiddleware 验证请求合法性。 |
| 必填 | **是** (生产环境) |
| 默认值 | 无默认值 |
| 示例 | `AGENTMESH_SECRET_KEY=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6` |
| 生成方式 | `python -c "import secrets; print(secrets.token_hex(32))"` (输出 64 字符 hex) |
| 验证 | Docker Compose 中 `${AGENTMESH_SECRET_KEY:?AGENTMESH_SECRET_KEY is required}` 确保必填 |

**安全注意事项**:

1. **禁止硬编码**: 不要在代码或配置文件中明文写入密钥
2. **使用密码管理器**: 将密钥存储在 1Password / HashiCorp Vault
3. **环境隔离**: 开发 / 测试 / 生产使用不同的密钥
4. **轮换周期**: 建议每 90 天轮换一次
5. **轮换步骤**:
   ```bash
   # 1. 生成新密钥
   NEW_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
   
   # 2. 更新环境变量
   export AGENTMESH_SECRET_KEY=$NEW_KEY
   
   # 3. 重启服务 (容器会重新加载 Env)
   docker compose -f scripts/docker-compose.prod.yml restart app
   ```

---

## 6. 可选外部服务

### `DATABASE_URL` (预留)

| 属性 | 值 |
|------|------|
| 描述 | 外部 PostgreSQL 数据库连接字符串。当前未实现, 预留用于后续从 SQLite 迁移到 PostgreSQL。 |
| 必填 | 否 |
| 默认值 | (空, 使用 SQLite) |
| 示例 | `DATABASE_URL=postgresql://user:password@host:5432/agentmesh` |
| 当前状态 | 未支持 (SQLite only) |

### `SENTRY_DSN` (预留)

| 属性 | 值 |
|------|------|
| 描述 | Sentry 错误监控的 DSN (Data Source Name)。用于实时错误追踪。 |
| 必填 | 否 |
| 默认值 | (空, 禁用 Sentry) |
| 示例 | `SENTRY_DSN=https://xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx@xxxxx.ingest.sentry.io/xxxxxx` |
| 当前状态 | 未集成 (预留变量) |

---

## 7. CLI 参数

AgentMesh 提供 `agentmesh` CLI 工具, 支持以下子命令:

### `serve` — 启动网关

```bash
# 默认启动 (:memory: DB, 8000 端口)
python -m agentmesh.cli serve

# 指定端口和数据库文件
python -m agentmesh.cli serve --port 8000 --db /var/lib/agentmesh/data/agentmesh_platform.db

# 指定绑定地址
python -m agentmesh.cli serve --host 127.0.0.1 --port 9000
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | `8000` | HTTP 监听端口 |
| `--host` | `0.0.0.0` | 绑定地址 |
| `--db` | `:memory:` | SQLite 数据库路径 (`:memory:` 为内存数据库) |

### `agents` — 列出已注册 Agent

```bash
python -m agentmesh.cli agents
python -m agentmesh.cli agents --db /var/lib/agentmesh/data/agentmesh_platform.db
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--db` | `:memory:` | 数据库路径 |

### `health` — 健康检查

```bash
python -m agentmesh.cli health
python -m agentmesh.cli health --host localhost --port 8000
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `localhost` | 网关地址 |
| `--port` | `8000` | 网关端口 |

---

## 8. 配置值校验

### Docker Compose 启动时校验

`docker-compose.prod.yml` 使用 Shell 参数展开进行强制校验:

```yaml
environment:
  - AGENTMESH_SECRET_KEY=${AGENTMESH_SECRET_KEY:?AGENTMESH_SECRET_KEY is required}
```

缺少 `AGENTMESH_SECRET_KEY` 时, `docker compose up` 会直接报错退出。

### 启动脚本校验

`scripts/start.sh` 设置 `PYTHONPATH` 后启动 CLI:

```bash
export PYTHONPATH="${PYTHONPATH:-}:${PROJECT_ROOT}"
cd "$PROJECT_ROOT"
exec python -m agentmesh.cli serve "$@"
```

环境变量缺失时, 应用层会通过默认值或运行时错误体现。

---

## 9. 配置生效路径一览

```
.env                                        # 用户创建, gitignore
├── AGENTMESH_DB_DIR  ──→ docker-compose.yml    (数据库目录)
│                      ──→ deps.py:init_db()    (连接初始化)
│                      ──→ db_schema.py         (Schema 执行)
├── AGENTMESH_LOG_LEVEL─→ logging_config.py     (日志级别)
├── AGENTMESH_LOG_DIR  ──→ logging_config.py    (日志文件目录)
├── AGENTMESH_HOST     ──→ docker-compose.yml   (绑定地址)
├── AGENTMESH_PORT     ──→ docker-compose.yml   (端口映射)
├── AGENTMESH_WORKERS  ──→ docker-compose.yml   (Worker 数)
└── AGENTMESH_SECRET_KEY─→ docker-compose.yml   (密钥注入)
                         ─→ gateway middleware  (认证)
```

未设置的环境变量使用代码中的默认值, Docker Compose 中的 Shell 默认值 (如 `${AGENTMESH_LOG_LEVEL:-info}`) 与代码默认值保持一致。

---

## 10. Makefile 快速命令

| 命令 | 说明 |
|------|------|
| `make lint` | 运行 ruff lint 检查 |
| `make format` | 自动格式化代码 |
| `make test` | 运行所有测试 (跳过 benchmarks) |
| `make test-platform` | 仅 platform 测试 (含覆盖率) |
| `make health` | 生成项目健康报告 |
| `make clean` | 清理缓存文件 |

---

## 参考

- [运维手册](README.md)
- [生产检查清单](production-checklist.md)
- [.env.prod.example](../../.env.prod.example)
- [docker-compose.prod.yml](../../scripts/docker-compose.prod.yml)
- [logging_config.py](../../agentmesh/platform/logging_config.py)
