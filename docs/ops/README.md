# AgentMesh 运维手册

> 版本: v1.0.0rc1 | 更新日期: 2026-06-09

涵盖 AgentMesh Platform 的部署、监控、排障与日常运维。适用于运维工程师和 SRE 团队。

---

## 1. 架构概览

AgentMesh 采用**单体网关 + SQLite 持久化**的轻量架构，所有服务通过单一 HTTP 网关对外暴露。

```
┌─────────────────────────────────────────────────────┐
│                  AgentMesh Gateway                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐ │
│  │ Identity  │  │   Task   │  │  Escrow  │  │Reput.│ │
│  │  Router   │  │  Market  │  │  Router  │  │Router│ │
│  └──────────┘  └──────────┘  └──────────┘  └──────┘ │
│  ┌──────────────────────────────────────────────┐   │
│  │           AuthMiddleware                      │   │
│  └──────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────┐   │
│  │            SQLite (WAL mode)                   │   │
│  │  10 tables: agents, tasks, evidence_chain,    │   │
│  │  accounts, transactions, reviews, ...          │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

- **API 网关**: FastAPI + uvicorn, 单进程多 Worker
- **数据层**: SQLite (WAL), 文件存储在 `/var/lib/agentmesh/data`
- **日志**: JSON 结构化日志, 输出到 stderr + 轮转文件
- **健康检查**: `GET /api/v1/health`

---

## 2. 部署

### 2.1 前置条件

| 组件 | 版本要求 | 备注 |
|------|----------|------|
| Python | >= 3.10 | 推荐 3.11 |
| Docker | >= 24.0 | 容器部署方式 |
| 磁盘 | >= 1 GB 空闲 | SQLite 数据库 + 日志 |
| 内存 | >= 256 MB | 基础运行, 推荐 512 MB+ |

### 2.2 Docker Compose 部署（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/wangxianjiangwxj-ctrl/agentmesh.git
cd agentmesh

# 2. 配置环境变量
cp .env.prod.example .env
# 编辑 .env, 务必设置 AGENTMESH_SECRET_KEY

# 3. 启动服务
docker compose -f scripts/docker-compose.prod.yml up -d

# 4. 确认启动成功
docker compose -f scripts/docker-compose.prod.yml ps
docker compose -f scripts/docker-compose.prod.yml logs app

# 5. 验证健康检查
curl http://localhost:8000/api/v1/health
# 预期: {"status": "ok", "version": "0.1.0"}
```

**生产 Compose 服务组成**:

| 服务 | 容器名 | 作用 | 寿命 |
|------|--------|------|------|
| `app` | agentmesh-app | FastAPI 网关 (主服务) | 持续运行 |
| `db-init` | agentmesh-db-init | 初始化数据库 Schema | 启动即退出 |

### 2.3 Docker 单容器部署

```bash
# 构建镜像
docker build -f scripts/Dockerfile -t agentmesh:latest .

# 运行
docker run -d \
  --name agentmesh \
  -p 8000:8000 \
  -v agentmesh_data:/var/lib/agentmesh \
  -e AGENTMESH_DB_DIR=/var/lib/agentmesh/data \
  -e AGENTMESH_SECRET_KEY=<your-secret-key> \
  agentmesh:latest
```

### 2.4 源码手动部署

```bash
# 1. 安装依赖
pip install -e .

# 2. 配置环境变量
export AGENTMESH_DB_DIR=/var/lib/agentmesh/data
export AGENTMESH_LOG_LEVEL=info
export AGENTMESH_PORT=8000
export AGENTMESH_WORKERS=4
export AGENTMESH_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# 3. 初始化数据目录
sudo bash scripts/init_data_dirs.sh

# 4. 启动服务
python -m agentmesh.cli serve --port 8000

# 5. 或使用 uvicorn 直接启动
uvicorn agentmesh.gateway.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 2.5 初始化数据目录

`scripts/init_data_dirs.sh` 脚本会创建以下目录结构:

```
/var/lib/agentmesh/
├── data/        # SQLite 数据库文件 (agentmesh_platform.db)
├── logs/        # JSON 轮转日志文件
└── backups/     # 数据库备份/快照
```

运行:
```bash
sudo bash scripts/init_data_dirs.sh
```

脚本会:
- 创建系统用户 `agentmesh:agentmesh`
- 创建上述三个目录, 权限 750
- 设置目录所属用户/组

---

## 3. 配置

核心配置通过环境变量注入。详见 [configuration.md](configuration.md)。

**必填配置**:

| 变量 | 说明 | 生成方式 |
|------|------|----------|
| `AGENTMESH_SECRET_KEY` | 会话签名密钥 | `python -c "import secrets; print(secrets.token_hex(32))"` |

**典型配置 (production)**:

```bash
AGENTMESH_DB_DIR=/var/lib/agentmesh/data
AGENTMESH_LOG_LEVEL=info
AGENTMESH_HOST=0.0.0.0
AGENTMESH_PORT=8000
AGENTMESH_WORKERS=4
AGENTMESH_SECRET_KEY=<generated-64-char-hex>
```

---

## 4. 监控

### 4.1 健康检查端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/health` | GET | 服务健康状态 + 版本号 |
| `/ping` | GET | A2A Server ping (轻量) |
| `/health` | GET | A2A Server 详细健康 (uptime + 组件状态) |

**健康检查示例**:

```bash
# Gateway 健康检查
curl http://localhost:8000/api/v1/health
# {"status": "ok", "version": "0.1.0"}

# 外部监控 (如 Prometheus Blackbox Exporter)
# probe: http_2xx, target: http://host:8000/api/v1/health
```

**Docker Compose 内置健康检查** (已在 `docker-compose.prod.yml` 中配置):

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 15s
```

### 4.2 日志系统

日志采用 JSON 结构化格式, 便于接入日志聚合系统 (Loki / ELK / Datadog)。

**日志输出**:

- **stderr (控制台)**: JSON 格式, 适合容器/系统日志采集
- **文件轮转**: 10 MB 每文件, 保留 5 个备份, 路径: `{AGENTMESH_LOG_DIR}/agentmesh.log`

**JSON 日志示例**:

```json
{"timestamp": "2026-06-09T14:30:00+00:00", "level": "INFO", "logger": "agentmesh", "module": "main", "function": "health", "line": 42, "message": "Server started", "extra": {"host": "0.0.0.0", "port": 8000}}
```

**日志级别**:

| 级别 | 生产 | 调试 |
|------|------|------|
| `debug` | 不推荐 | 详细调试 |
| `info` | 推荐 | 常规日志 |
| `warning` | 可配置 | 需关注事件 |
| `error` | 备用 | 错误上报 |

**采集建议**:

```bash
# 使用 journald 采集容器日志
docker compose -f scripts/docker-compose.prod.yml logs -f --tail=100 app

# 使用 Loki + Promtail 采集
# promtail 配置: scrape docker 容器 agentmesh-app 的 json-file 日志
```

### 4.3 CI 健康报告

GitHub Actions 每周一 `06:00 UTC` 自动运行项目健康检查, 输出评分报告。

配置在 `.github/workflows/health-check.yml`, 包括:
- ruff lint 静态检查
- pytest + coverage 测试覆盖
- `scripts/project_health_report.py` 综合评分

### 4.4 资源限制建议

Docker Compose 生产配置已包含资源限制:

```yaml
deploy:
  resources:
    limits:
      cpus: "2.0"        # 最大 2 核
      memory: "512M"     # 最大 512 MB
    reservations:
      cpus: "0.5"        # 保留 0.5 核
      memory: "128M"     # 保留 128 MB
```

- **CPU**: 根据 Worker 数调整。`AGENTMESH_WORKERS=2-4` 对应 1-2 核足够
- **内存**: SQLite 场景下 256-512 MB 充足。如启用大量并发 Agent, 可增至 1 GB
- **磁盘**: 日志轮转控制 50 MB 以内; 数据库在 1000 Agent / 10000 任务场景下约 50 MB

---

## 5. 备份与恢复

### 5.1 SQLite 数据库备份

SQLite 使用 WAL 模式, 支持热备份:

```bash
#!/bin/bash
# scripts/backup_db.sh

BACKUP_DIR="/var/lib/agentmesh/backups"
DB_PATH="/var/lib/agentmesh/data/agentmesh_platform.db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/agentmesh_platform_${TIMESTAMP}.db"

sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"
gzip "${BACKUP_FILE}"
echo "Backup completed: ${BACKUP_FILE}.gz"

# 清理 30 天前的旧备份
find "${BACKUP_DIR}" -name "agentmesh_platform_*.db.gz" -mtime +30 -delete
```

### 5.2 恢复

```bash
gunzip -k /var/lib/agentmesh/backups/agentmesh_platform_20260609_143000.db.gz
cp agentmesh_platform_20260609_143000.db /var/lib/agentmesh/data/agentmesh_platform.db
docker restart agentmesh-app
```

### 5.3 备份策略建议

| 频率 | 类型 | 保留 |
|------|------|------|
| 每日 | 完整 SQLite backup | 7 天 |
| 每周 | 完整 + 压缩归档 | 4 周 |
| 每月 | 完整 + 异地存储 | 12 个月 |

---

## 6. 升级

### 6.1 版本升级流程

```bash
# 1. 拉取新版本
git pull origin main

# 2. 备份数据库
sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db ".backup 'backup_before_upgrade.db'"

# 3. 重建容器
docker compose -f scripts/docker-compose.prod.yml down
docker compose -f scripts/docker-compose.prod.yml build
docker compose -f scripts/docker-compose.prod.yml up -d

# 4. 验证升级
curl http://localhost:8000/api/v1/health
# 确认返回新版本号
```

### 6.2 数据库 Schema 迁移

当前使用 `CREATE TABLE IF NOT EXISTS` 模式, 新版本新增表会自动创建。**不自动修改已有表结构**。

Schema 变更时需手动执行迁移脚本:

```python
# scripts/migrate_v1_to_v2.py
import sqlite3

conn = sqlite3.connect("/var/lib/agentmesh/data/agentmesh_platform.db")
conn.execute("PRAGMA journal_mode=WAL;")

# 检查表是否存在
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
table_names = {t[0] for t in tables}

# 如果需要新增表
if "new_table" not in table_names:
    conn.execute("CREATE TABLE IF NOT EXISTS new_table (...)")
    conn.commit()
    print("New table created")

conn.close()
```

---

## 7. 安全

### 7.1 密钥管理

| 密钥 | 用途 | 管理方式 |
|------|------|----------|
| `AGENTMESH_SECRET_KEY` | 会话签名 / Token 加密 | 使用密码管理器 (1Password/Vault) |
| API Keys | Agent 身份认证 | 数据库存储, 生产环境考虑外部 KMS |

**密钥轮换**:

```bash
# 生成新密钥
NEW_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# 更新环境变量并重启
export AGENTMESH_SECRET_KEY=$NEW_KEY
docker compose -f scripts/docker-compose.prod.yml restart app
```

### 7.2 网络安全

生产环境建议:

- 网关仅暴露 `AGENTMESH_PORT` (默认 8000)
- 使用反向代理 (Nginx / Caddy) 处理 TLS 终止
- 启用 `Content-Security-Policy` 等安全头
- Web UI 管理面板限制内网访问

详见 [安全指南](../security/README.md)。

---

## 8. 性能调优

### 8.1 Worker 数

```bash
# CPU 密集场景: 每个 CPU 核 2 Worker
AGENTMESH_WORKERS=$(($(nproc) * 2))

# I/O 密集场景 (SQLite): 每个 CPU 核 1-2 Worker
AGENTMESH_WORKERS=$(($(nproc) * 1))
```

### 8.2 SQLite WAL 模式

数据库已默认启用 WAL (Write-Ahead Logging) 模式, 提升并发读写性能。

```sql
-- 确认 WAL 模式
PRAGMA journal_mode;
-- 输出: wal

-- WAL 文件维护 (建议定时执行)
PRAGMA wal_checkpoint(TRUNCATE);
```

### 8.3 日志性能

- 生产环境使用 `info` 级别, 避免 `debug`
- 文件日志轮转: 10 MB/文件, 保留 5 份
- CPU 紧张时可关闭文件日志, 仅保留 stderr 输出

---

## 9. 故障排查

### 9.1 服务不可达

```bash
# 步骤 1: 检查容器状态
docker ps | grep agentmesh

# 步骤 2: 检查端口监听
netstat -tlnp | grep 8000
lsof -i :8000

# 步骤 3: 检查容器日志
docker logs agentmesh-app --tail 50

# 步骤 4: 尝试健康检查
curl -v http://localhost:8000/api/v1/health
```

### 9.2 数据库问题

```bash
# SQLite 完整性检查
sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db "PRAGMA integrity_check;"
# 输出: ok

# 重建索引
sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db "REINDEX;"
```

### 9.3 性能问题

```bash
# 检查慢查询
sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db "PRAGMA query_only=0;"
sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db ".timer on"

# 检查数据库大小
ls -lh /var/lib/agentmesh/data/agentmesh_platform.db
ls -lh /var/lib/agentmesh/data/agentmesh_platform.db-wal
ls -lh /var/lib/agentmesh/data/agentmesh_platform.db-shm

# WAL 文件过大时执行 checkpoint
sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

### 9.4 日志排障速查

| 日志关键词 | 可能原因 | 处理方式 |
|------------|----------|----------|
| `Cannot create rotating file handler` | 日志目录不可写 | 检查 AGENTMESH_LOG_DIR 权限 |
| `Secret key not set` | AGENTMESH_SECRET_KEY 未配置 | 设置密钥 |
| `Connection refused` | 端口被占用或服务未启动 | 检查端口/启动服务 |
| `Database is locked` | SQLite 写并发过高 | 减少 Worker 数或迁移到 PostgreSQL |

### 9.5 常见错误码

| HTTP 状态码 | 含义 | 排查方向 |
|-------------|------|----------|
| 400 | 请求参数错误 | 检查请求体格式 |
| 404 | 资源不存在 | 确认 Agent/Task ID |
| 500 | 服务器内部错误 | 查看日志获取 traceback |
| 503 | 服务不可用 | 检查负载/超时配置 |

更多排障: 参见 [故障排查指南](../../docs/troubleshooting.md)。

---

## 10. 日常运维任务

### 10.1 每日检查

- [ ] 健康检查端点返回 `status: ok`
- [ ] 容器日志无 `ERROR` 级别输出
- [ ] 数据库文件大小正常 (无异常增长)

### 10.2 每周检查

- [ ] 查看备份文件是否正确生成
- [ ] 检查 WAL 文件大小 (< 100 MB)
- [ ] 审查日志错误, 排查潜在问题

### 10.3 每月检查

- [ ] 清理 30 天前的日志文件和数据库备份
- [ ] 执行 `PRAGMA integrity_check` 数据库完整性验证
- [ ] 检查磁盘使用率
- [ ] 审查安全更新, 升级依赖版本

---

## 参考

- [配置参考](configuration.md)
- [生产检查清单](production-checklist.md)
- [安全指南](../security/README.md)
- [故障排查指南](../../docs/troubleshooting.md)
- [Docker Compose 配置](../../scripts/docker-compose.prod.yml)
- [Dockerfile](../../scripts/Dockerfile)
