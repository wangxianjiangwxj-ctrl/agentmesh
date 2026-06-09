# AgentMesh 生产检查清单

> 版本: v1.0.0rc1 | 更新日期: 2026-06-09

生产环境部署/运维一站式检查清单, 覆盖部署前、部署后和日常运维三个阶段。

---

## 1. 部署前检查

### 1.1 环境准备

- [ ] 确认目标主机满足最低要求
  - Python >= 3.10 (推荐 3.11)
  - Docker >= 24.0 (容器部署)
  - 磁盘空闲 >= 1 GB
  - 内存 >= 512 MB

- [ ] Docker 安装确认
  ```bash
  docker --version
  docker compose version
  ```

- [ ] 网络确认
  ```bash
  curl -I https://pypi.org  # 可拉取 Python 依赖
  curl -I https://ghcr.io   # 可拉取 Docker 镜像 (如使用 ghcr)
  ```

### 1.2 代码与版本

- [ ] 代码从合法 Tag 或 Release 分支拉取
  ```bash
  git tag -l 'v*'     # 确认可用版本
  git checkout v1.0.0rc1
  ```

- [ ] 确认 CHANGELOG 包含当前版本的完整变更记录

- [ ] 确认 `pyproject.toml` 版本号正确

### 1.3 配置

- [ ] `.env` 文件已从 `.env.prod.example` 复制并填写
  ```bash
  cp .env.prod.example .env
  ```

- [ ] **`AGENTMESH_SECRET_KEY` 已设置** (生产必填项)
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  # 将输出复制到 .env 的 AGENTMESH_SECRET_KEY 字段
  ```

- [ ] 所有环境变量按预期配置:
  - `AGENTMESH_DB_DIR` --- 数据库存储路径, 确保该目录已创建且可写
  - `AGENTMESH_LOG_LEVEL=info` --- 生产环境使用 info, 非 debug
  - `AGENTMESH_PORT` --- 未被其他进程占用
  - `AGENTMESH_WORKERS` --- 根据 CPU 核数配置 (建议 2-4)

- [ ] 密钥未硬编码在任何文件中, 仅通过 `.env` 注入

### 1.4 数据目录

- [ ] 数据目录已初始化
  ```bash
  sudo bash scripts/init_data_dirs.sh
  ```

- [ ] 目录权限正确:
  ```bash
  ls -la /var/lib/agentmesh/
  # 预期: data/ logs/ backups/
  # 所有目录权限 750, 属主 agentmesh:agentmesh
  ```

- [ ] 数据库文件未残留在目标路径 (如需全新部署, 确认无旧的 `.db` 文件)

### 1.5 安全

- [ ] 数据库和日志目录的权限为 750, 非其他用户可读
- [ ] `.env` 文件权限为 600 (仅属主可读写)
  ```bash
  chmod 600 .env
  ```
- [ ] `.gitignore` 已包含 `.env` (确认仓库中无 `.env` 文件)
- [ ] 防火墙已放行所需端口 (默认 8000/TCP)
- [ ] 如暴露公网, 前方配置了反向代理 (Nginx / Caddy) 处理 TLS

---

## 2. 部署后检查

### 2.1 服务启动

- [ ] Docker 容器成功启动
  ```bash
  docker compose -f scripts/docker-compose.prod.yml up -d
  docker compose -f scripts/docker-compose.prod.yml ps
  # 预期: agentmesh-app 状态 Up, agentmesh-db-init 状态 Exited (0)
  ```

- [ ] db-init 日志确认 Schema 初始化成功
  ```bash
  docker logs agentmesh-db-init
  # 预期: "Database initialized at /var/lib/agentmesh/data/agentmesh_platform.db"
  ```

- [ ] 应用容器日志无 ERROR
  ```bash
  docker logs agentmesh-app --tail 50 | grep -i error
  # 预期: 无输出
  ```

### 2.2 健康检查

- [ ] 基础健康检查通过
  ```bash
  curl http://localhost:8000/api/v1/health
  # 预期: {"status": "ok", "version": "0.1.0"}
  ```

- [ ] Docker 内置健康检查通过
  ```bash
  docker inspect agentmesh-app | jq '.[].State.Health.Status'
  # 预期: "healthy"
  ```

- [ ] A2A Server 可用 (如启用)
  ```bash
  curl http://localhost:8000/ping
  # 预期: {"success": true, "data": {"status": "ok", "provider": "http"}, ...}
  ```

### 2.3 数据库验证

- [ ] 数据库文件已创建
  ```bash
  ls -lh /var/lib/agentmesh/data/
  # 预期: agentmesh_platform.db 存在且大小 > 0
  ```

- [ ] 数据库 Schema 验证
  ```bash
  sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db ".tables"
  # 预期: agents, tasks, evidence_chain, accounts, transactions, reviews, ...
  ```

- [ ] 数据库完整性检查
  ```bash
  sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db "PRAGMA integrity_check;"
  # 预期: ok
  ```

- [ ] WAL 模式确认
  ```bash
  sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db "PRAGMA journal_mode;"
  # 预期: wal
  ```

### 2.4 日志验证

- [ ] 日志文件已创建
  ```bash
  ls -lh /var/lib/agentmesh/logs/
  # 预期: agentmesh.log 存在
  ```

- [ ] 日志内容为有效 JSON
  ```bash
  head -1 /var/lib/agentmesh/logs/agentmesh.log | python -c "import json,sys; json.load(sys.stdin); print('Valid JSON')"
  # 预期: Valid JSON
  ```

### 2.5 功能验证

- [ ] HTTP API 可正常响应
  ```bash
  curl -s http://localhost:8000/api/v1/health | python -c "import json,sys; d=json.load(sys.stdin); assert d['status']=='ok'; print('API OK')"
  ```

- [ ] 注册 Agent (如启用注册功能)
  ```bash
  curl -X POST http://localhost:8000/agents \
    -H "Content-Type: application/json" \
    -d '{"name": "test-agent", "skills": ["test"]}'
  # 预期: {"success": true, ...}
  ```

### 2.6 备份验证

- [ ] 首次备份成功执行
  ```bash
  sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db ".backup '/var/lib/agentmesh/backups/initial.db'"
  ls -lh /var/lib/agentmesh/backups/
  ```

---

## 3. 日常检查

### 3.1 每日检查 (建议定时任务)

- [ ] **健康检查**: 端点返回 `status: ok`
  ```bash
  curl -sf http://localhost:8000/api/v1/health > /dev/null && echo "OK" || echo "FAIL"
  ```

- [ ] **容器状态**: 所有容器正常运行
  ```bash
  docker ps --filter "status=exited" --filter "name=agentmesh" | grep -q "agentmesh-app" && echo "WARN: app exited" || echo "OK"
  ```

- [ ] **日志错误**: 24 小时内无 ERROR 日志
  ```bash
  journalctl -u docker --since "24 hours ago" | grep "agentmesh.*ERROR" | wc -l
  # 预期: 0
  ```

- [ ] **磁盘使用率**: 低于 80%
  ```bash
  df -h /var/lib/agentmesh | tail -1 | awk '{print $5}' | sed 's/%//'
  # 预期: < 80
  ```

### 3.2 每周检查

- [ ] **数据库备份**: 检查备份文件是否正常生成
  ```bash
  ls -lh /var/lib/agentmesh/backups/ | head -5
  ```

- [ ] **WAL 文件大小**: 检查 WAL 文件是否异常增长
  ```bash
  ls -lh /var/lib/agentmesh/data/agentmesh_platform.db-wal 2>/dev/null || echo "WAL not exists"
  # 如超过 100 MB, 执行 checkpoint
  ```

- [ ] **数据库文件大小趋势**: 对比上周大小
  ```bash
  ls -lh /var/lib/agentmesh/data/agentmesh_platform.db
  ```

- [ ] **日志文件轮转**: 确认日志文件没有无限增长
  ```bash
  ls -lh /var/lib/agentmesh/logs/
  # 总大小应控制在 50 MB 以内 (10 MB x 5 轮转 + 当前)
  ```

### 3.3 每月检查

- [ ] **数据库完整性**: 执行完整性检查
  ```bash
  sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db "PRAGMA integrity_check;"
  # 预期: ok
  ```

- [ ] **数据库重建索引**: 优化查询性能
  ```bash
  sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db "REINDEX;"
  ```

- [ ] **WAL Checkpoint**: 执行 WAL checkpoint 并缩容
  ```bash
  sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db "PRAGMA wal_checkpoint(TRUNCATE);"
  ```

- [ ] **旧备份清理**: 删除 30 天前的备份
  ```bash
  find /var/lib/agentmesh/backups -name "*.db.gz" -mtime +30 -delete
  ```

- [ ] **磁盘使用率趋势**: 确认月度增长在预期范围内
  ```bash
  du -sh /var/lib/agentmesh/
  ```

- [ ] **依赖安全检查**: 运行 CVE 扫描
  ```bash
  pip-audit --strict
  ```

### 3.4 发布后检查

- [ ] **版本号确认**: 确认新版本正确部署
  ```bash
  curl http://localhost:8000/api/v1/health | python -c "import json,sys; print(json.load(sys.stdin)['version'])"
  ```

- [ ] **Schema 更新**: 如有新表, 确认已创建
  ```bash
  sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db ".tables"
  ```

- [ ] **回归测试**: 运行关键功能测试
  ```bash
  python -m pytest tests/platform/ -q --tb=short
  ```

---

## 4. 回滚流程

### 4.1 Docker Compose 回滚

```bash
# 1. 拉取上一个版本的代码
git checkout <previous-tag>

# 2. 备份当前数据库 (如有 Schema 变更, 可能需要恢复旧 Schema)
sqlite3 /var/lib/agentmesh/data/agentmesh_platform.db ".backup 'rollback_backup.db'"

# 3. 重建并启动旧版本
docker compose -f scripts/docker-compose.prod.yml down
docker compose -f scripts/docker-compose.prod.yml build
docker compose -f scripts/docker-compose.prod.yml up -d

# 4. 验证回滚成功
curl http://localhost:8000/api/v1/health
```

### 4.2 数据库回滚

如果新版本引入了 Schema 变更且需要回退:

```bash
# 1. 停止服务
docker compose -f scripts/docker-compose.prod.yml down

# 2. 从备份恢复旧数据库
cp /var/lib/agentmesh/backups/agentmesh_platform_<pre-deploy-date>.db \
   /var/lib/agentmesh/data/agentmesh_platform.db

# 3. 启动旧版本服务
docker compose -f scripts/docker-compose.prod.yml up -d
```

> 注意: 数据库 Schema 回滚可能导致数据丢失。请在部署前确保备份完整。

---

## 5. 自动化巡检脚本

### 5.1 Shell 巡检脚本

将以下脚本保存为 `scripts/health_check.sh`, 配合 cron 使用:

```bash
#!/bin/bash
# scripts/health_check.sh — 生产巡检脚本

set -euo pipefail

HOST=${HEALTH_CHECK_HOST:-localhost}
PORT=${HEALTH_CHECK_PORT:-8000}
DB_PATH=${HEALTH_CHECK_DB:-/var/lib/agentmesh/data/agentmesh_platform.db}
LOG_DIR=${HEALTH_CHECK_LOG:-/var/lib/agentmesh/logs}
ALERT_EMAIL="ops@example.com"

echo "=== AgentMesh 健康巡检 $(date '+%Y-%m-%d %H:%M:%S') ==="

# 1. HTTP 健康检查
HTTP_STATUS=$(curl -sf "http://${HOST}:${PORT}/api/v1/health" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','FAIL'))" 2>/dev/null || echo "FAIL")
echo "Health check: ${HTTP_STATUS}"
if [[ "$HTTP_STATUS" != "ok" ]]; then
    echo "ALERT: Health check failed" | mail -s "AgentMesh Health Alert" "$ALERT_EMAIL"
fi

# 2. 数据库完整性
DB_INTEGRITY=$(sqlite3 "$DB_PATH" "PRAGMA integrity_check;" 2>/dev/null)
echo "DB integrity: ${DB_INTEGRITY}"
if [[ "$DB_INTEGRITY" != "ok" ]]; then
    echo "ALERT: Database corruption detected" | mail -s "AgentMesh DB Alert" "$ALERT_EMAIL"
fi

# 3. 磁盘使用率
DISK_USAGE=$(df /var/lib/agentmesh | tail -1 | awk '{print $5}' | sed 's/%//')
echo "Disk usage: ${DISK_USAGE}%"
if [[ "$DISK_USAGE" -gt 80 ]]; then
    echo "ALERT: Disk usage > 80%" | mail -s "AgentMesh Disk Alert" "$ALERT_EMAIL"
fi

# 4. 日志错误检查
ERROR_COUNT=$(grep -c '"level":"ERROR"' "$LOG_DIR/agentmesh.log" 2>/dev/null || echo 0)
echo "Log errors (last rotation): ${ERROR_COUNT}"
if [[ "$ERROR_COUNT" -gt 0 ]]; then
    echo "RECOMMENDATION: Review $LOG_DIR/agentmesh.log for errors"
fi

echo "=== 巡检完成 ==="
```

### 5.2 Cron 配置

```cron
# 每日 08:00 和 20:00 执行巡检
0 8,20 * * * /usr/local/bin/agentmesh-health-check.sh

# 每周日 03:00 执行全量备份
0 3 * * 0 /usr/local/bin/agentmesh-backup.sh

# 每月 1 日 04:00 执行数据库维护
0 4 1 * * /usr/local/bin/agentmesh-maintenance.sh
```

---

## 6. 指标与阈值速查

| 指标 | 健康阈值 | 警告阈值 | 危险阈值 | 检查方式 |
|------|----------|----------|----------|----------|
| 健康检查响应 | `status: ok` | 超时 5s+ | 连通失败 | `curl /api/v1/health` |
| 数据库完整性 | `ok` | — | 非 `ok` | `PRAGMA integrity_check` |
| 磁盘使用率 | < 60% | 60-80% | > 80% | `df /var/lib/agentmesh` |
| 内存使用率 | < 60% | 60-80% | > 80% | `docker stats agentmesh-app` |
| CPU 使用率 | < 50% | 50-80% | > 80% | `docker stats agentmesh-app` |
| WAL 文件大小 | < 10 MB | 10-100 MB | > 100 MB | `ls -lh *.db-wal` |
| 日志总大小 | < 20 MB | 20-50 MB | > 50 MB | `du -sh /var/lib/agentmesh/logs` |
| 响应延迟 (p99) | < 100 ms | 100-500 ms | > 500 ms | 外部监控 |
| 容器健康检查 | healthy | — | unhealthy | `docker inspect` |

---

## 参考

- [运维手册](README.md)
- [配置参考](configuration.md)
- [安全指南](../security/README.md)
- [Release 检查清单](../../docs/release-checklist.md)
- [docker-compose.prod.yml](../../scripts/docker-compose.prod.yml)
