# AgentMesh Makefile — 本地开发常用命令

PYTHON = python3
RUFF = ruff
PYTEST = python3 -m pytest

.PHONY: help lint format test test-quiet health clean

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

lint: ## 运行 ruff lint 检查
	$(RUFF) check .

format: ## 自动格式化代码
	$(RUFF) format .

test: ## 运行所有测试（跳过 benchmarks）
	$(PYTEST) tests/ --ignore=tests/benchmarks -v --tb=short

test-quiet: ## 运行测试（简洁输出）
	$(PYTEST) tests/ --ignore=tests/benchmarks -q --tb=short

test-platform: ## 仅 platform 测试（含覆盖率）
	$(PYTEST) tests/platform/ --cov=agentmesh/platform --cov-report=term-missing -q --tb=short

health: ## 生成项目健康报告
	$(PYTHON) scripts/project_health_report.py

clean: ## 清理缓存和临时文件
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .ruff_cache
