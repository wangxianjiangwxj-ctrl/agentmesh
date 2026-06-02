# E2E 集成测试客户端

## 用途

本目录包含连接 中书令 A2A 测试 Server 的客户端测试脚本，用于 Phase 14 方向A（真实集成测试）。

## 测试场景

### 1. 双向保真度验证 (test_bidirectional_fidelity.py)
- AgentMesh CLI serve → A2A Server connect → 任务下发 → 结果回传
- 验证 agentmesh 的 `connect` 命令能正确连接到 A2A Server
- 验证任务提交和结果获取的完整往返

### 2. 贡献度跨协议保留验证 (test_contribution_preservation.py)
- 任务通过 agentmesh 提交到 A2A Server
- 检查 `task_history` 中的贡献度元数据是否保留
- 检查 `source` 字段在协议转换中是否正确传递

### 3. 多任务并发 (test_concurrent_tasks.py)
- 同时向 A2A Server 提交多个任务
- 验证并发处理能力和结果关联

### 4. 错误恢复 (test_error_recovery.py)
- 模拟连接中断、超时、无效响应
- 验证 agentmesh 客户端的错误处理和重试机制

## 使用方式

```bash
# 启动测试 Server（由中书令提供）
cd /path/to/a2a-test-server
python a2a_test_server.py  # 默认端口 8000

# 运行 E2E 测试
cd ~/.openclaw/workspace/shangshuling/agentmesh
python -m pytest tests/e2e/ -v --server-url=http://localhost:8000
```

## 依赖

- Python 3.10+
- agentmesh SDK
- requests (用于直接 HTTP 调用 A2A Server)
