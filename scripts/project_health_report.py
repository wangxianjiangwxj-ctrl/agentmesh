#!/usr/bin/env python3
"""AgentMesh 项目健康报告生成脚本。

扫描 agentmesh/ 和 tests/ 目录，统计代码指标，运行 lint/测试检查，
输出 Markdown 格式的健康报告。

使用方式:
    python scripts/project_health_report.py [--output-dir DIR]
"""

import argparse
import ast
import datetime
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

PROJECT_DIR = Path(__file__).resolve().parent.parent
PYTHON_SUFFIX = ".py"
MAX_SCORE = 100


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def _run_cmd(cmd: list, timeout: int = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"timeout ({timeout}s): {' '.join(cmd)}"


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _find_py_files(root: Path, max_files: int = 500) -> list[Path]:
    """Recursively find all .py files under root, excluding common noise dirs."""
    excluded_patterns = (
        "__pycache__", ".pytest_cache", ".ruff_cache", ".git",
        "venv", ".venv", "node_modules", ".egg-info",
    )
    py_files: list[Path] = []
    for f in sorted(root.rglob(f"*{PYTHON_SUFFIX}")):
        if any(p in f.parts for p in excluded_patterns):
            continue
        py_files.append(f)
        if len(py_files) >= max_files:
            break
    return py_files


def _count_lines(filepath: Path) -> int:
    try:
        with open(filepath, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _analyze_ast(filepath: Path) -> dict[str, int]:
    """Return counts: functions, classes, docstrings, lines."""
    counts: dict[str, int] = {"functions": 0, "classes": 0, "docstrings": 0, "lines": 0}
    try:
        with open(filepath) as f:
            tree = ast.parse(f.read())
        counts["lines"] = _count_lines(filepath)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                counts["functions"] += 1
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Constant, ast.Str)):
                    counts["docstrings"] += 1
            elif isinstance(node, ast.ClassDef):
                counts["classes"] += 1
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Constant, ast.Str)):
                    counts["docstrings"] += 1
    except (SyntaxError, OSError):
        pass
    return counts


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _ruff_check(root: Path) -> tuple[int, str]:
    rc, out, err = _run_cmd([sys.executable, "-m", "ruff", "check", "--statistics", str(root)])
    if rc == -1:
        return 0, "ruff not installed"
    # Count unique error codes from "N  Fxxx  ..." lines
    errors: set[str] = set()
    for line in out.splitlines():
        m = re.match(r"^\d+\s+(E|F|W|ANN|D|N|UP|SIM|RUF|I|B|A|C4|ARG|RET|PT|TRY|PTH)", line)
        if m:
            errors.add(m.group(1))
    return len(errors), out[:2000] if out else ""


def _test_count(root: Path) -> tuple[int, int, str]:
    """Return (passed, total, detail_text). Uses platform tests only for speed."""
    rc, out, err = _run_cmd([
        "python3", "-m", "pytest", str(root / "tests/platform"),
        "--tb=no", "-q",
    ])
    if rc == -1:
        return 0, 0, "pytest not installed"
    # Parse "N passed, M skipped, X errors" or "N passed"
    passed = 0
    skipped = 0
    errors = 0
    for line in out.splitlines():
        m = re.search(r"(\d+)\s+passed", line)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+)\s+skipped", line)
        if m:
            skipped = int(m.group(1))
        m = re.search(r"(\d+)\s+error", line)
        if m:
            errors = int(m.group(1))
    total = passed + skipped
    return passed, total, f"{passed} passed, {skipped} skipped, {errors} errors" if rc == 0 else f"{passed} passed (warnings)"


def _coverage_report(root: Path) -> tuple[float, str]:
    """Return (coverage_percent, detail_text). Platform-only for speed."""
    rc, out, err = _run_cmd([
        "python3", "-m", "pytest", str(root / "tests/platform"),
        "--cov=agentmesh/platform", "--cov-report=term-missing",
        "--tb=no", "-q",
    ])
    if rc == -1:
        return 0.0, "coverage not installed"
    # Parse TOTAL line
    for line in out.splitlines():
        m = re.match(r"TOTAL\s+(\d+)\s+(\d+)\s+(\d+)%", line)
        if m:
            covered = int(m.group(1)) - int(m.group(2))
            total = int(m.group(1))
            return round(covered / total * 100, 1) if total else 0.0, line
    return 0.0, out[:500]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_health(
    files: int, total_lines: int, doc_ratio: float,
    test_passed: int, test_total: int,
    lint_errors: int, coverage: float,
) -> tuple[int, list[str]]:
    """Compute health score (0-100) with breakdown."""
    score = 50  # base
    details: list[str] = []

    # Files & size (max 5)
    if files >= 30:
        score += 5
        details.append("+5: sufficient file count (>=30)")

    # Docstring ratio (max 15)
    if doc_ratio >= 90:
        score += 15
        details.append("+15: docstring ratio >= 90%")
    elif doc_ratio >= 70:
        score += 10
        details.append("+10: docstring ratio >= 70%")
    elif doc_ratio >= 50:
        score += 5
        details.append("+5: docstring ratio >= 50%")

    # Test pass rate (max 15)
    if test_total > 0:
        pass_rate = test_passed / test_total
        if pass_rate >= 0.95:
            score += 15
            details.append("+15: test pass rate >= 95%")
        elif pass_rate >= 0.80:
            score += 10
            details.append("+10: test pass rate >= 80%")
        elif pass_rate >= 0.60:
            score += 5
            details.append("+5: test pass rate >= 60%")

    # Lint errors (max 10)
    if lint_errors == 0:
        score += 10
        details.append("+10: zero lint errors")
    elif lint_errors <= 5:
        score += 5
        details.append(f"+5: low lint errors ({lint_errors})")

    # Coverage (max 5 — 网关0%拉低总分)
    if coverage >= 80:
        score += 5
        details.append(f"+5: code coverage >= 80% ({coverage}%)")
    elif coverage >= 50:
        score += 3
        details.append(f"+3: code coverage >= 50% ({coverage}%)")
    elif coverage >= 30:
        score += 1
        details.append(f"+1: code coverage >= 30% ({coverage}%)")

    return min(score, MAX_SCORE), details


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(output_dir: Optional[Path] = None) -> dict[str, Any]:
    """Run all checks, compute score, write report file, return data dict."""
    root = PROJECT_DIR
    out_dir = output_dir or root

    # 1. Scan Python files
    py_files = _find_py_files(root)
    total_lines = 0
    total_functions = 0
    total_classes = 0
    total_docstrings = 0
    for f in py_files:
        info = _analyze_ast(f)
        total_lines += info["lines"]
        total_functions += info["functions"]
        total_classes += info["classes"]
        total_docstrings += info["docstrings"]

    # 2. Docstring ratio
    total_defs = total_functions + total_classes
    doc_ratio = round(total_docstrings / total_defs * 100, 1) if total_defs else 100.0

    # 3. Lint
    lint_errors, lint_detail = _ruff_check(root)

    # 4. Tests
    test_passed, test_total, test_detail = _test_count(root)

    # 5. Coverage
    coverage, cov_detail = _coverage_report(root)

    # 6. Score
    score, score_details = _score_health(
        len(py_files), total_lines, doc_ratio,
        test_passed, test_total, lint_errors, coverage,
    )

    # 7. Grade
    if score >= 90:
        grade = "A (优秀)"
    elif score >= 75:
        grade = "B (良好)"
    elif score >= 60:
        grade = "C (合格)"
    elif score >= 40:
        grade = "D (待改进)"
    else:
        grade = "F (需修复)"

    # Build report
    report = f"""# AgentMesh 项目健康报告

**生成时间**: {_now()}
**项目目录**: {root}

## 概要

| 指标 | 数值 |
|------|------|
| Python 文件数 | {len(py_files)} |
| 总代码行数 | {total_lines} |
| 函数数 | {total_functions} |
| 类数 | {total_classes} |
| Docstring 覆盖率 | {doc_ratio}% |
| Lint 错误数 | {lint_errors} |
| 测试通过 | {test_passed}/{test_total} |
| 代码覆盖率 | {coverage}% |

## 评分明细

- **最终评分**: {score}/{MAX_SCORE}
- **评级**: {grade}

### 加分项
""" + "\n".join(f"- {d}" for d in score_details) + f"""

## 详细检查结果

### Lint 检查
```text
{lint_detail}
```

### 测试结果
```text
{test_detail}
```

### 代码覆盖率
```text
{cov_detail}
```
"""

    # Write report
    report_path = out_dir / f"project-health-report-{_today()}.md"
    report_path.write_text(report)
    print(f"Report written: {report_path}")

    return {
        "files": len(py_files),
        "total_lines": total_lines,
        "functions": total_functions,
        "classes": total_classes,
        "doc_ratio": doc_ratio,
        "lint_errors": lint_errors,
        "test_passed": test_passed,
        "test_total": test_total,
        "coverage": coverage,
        "score": score,
        "grade": grade,
        "report_path": str(report_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentMesh Health Report")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory")
    args = parser.parse_args()
    generate_report(args.output_dir)


if __name__ == "__main__":
    main()
