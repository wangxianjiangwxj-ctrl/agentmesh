# AgentMesh 安全指南总纲

> 版本: v1.0.0rc1 | 更新日期: 2026-06-09

本文汇总 AgentMesh 平台的安全审计结果, 包括 SQL 注入审计和 Web UI 安全审计的核心发现及修复建议。目标是为开发团队提供统一的安全参考和行动优先级。

---

## 1. 安全审计概况

| 审计项目 | 审计日期 | 文件范围 | 风险等级 |
|----------|----------|----------|----------|
| SQL 注入审计 | 2026-06-09 | `agentmesh/platform/` (22 个 Python 文件) | **低** |
| Web UI 安全审计 | 2026-06-09 | `gateway/templates/` (15 个 HTML 模板) + `web_ui.py` | **中** |

---

## 2. SQL 注入审计结果

### 2.1 审计方法

对所有 `conn.execute()` 和 `cursor.execute()` 调用进行分类检查:

| 分类 | 安全等级 | 说明 |
|------|----------|------|
| 参数化查询 (Safe) | 安全 | 用户值通过 `?` 占位符传入, 非字符串拼接 |
| 常量 f-string (Safe) | 低风险 | f-string 仅含硬编码常量表名, 用户值仍参数化 |
| 用户输入拼接 (高风险) | 未发现 | 无用户控制值直接拼接入 SQL |

### 2.2 统计结果

| 指标 | 值 |
|------|------|
| 扫描文件数 | 22 |
| SQL 执行点审查 | ~120 处 |
| 确认注入风险 | **0** |
| 最佳实践偏离 (低风险) | **3 处** |
| 综合风险等级 | **低** |

### 2.3 核心发现

**用户输入全部参数化**, 所有 `conn.execute()` 均使用 `?` 占位符。代表性安全代码:

```python
# 安全: 所有用户值通过 ? 占位符传递
row = self.conn.execute(
    "SELECT * FROM agents WHERE id = ?", (agent_id,)
).fetchone()

db.execute(
    "INSERT INTO companies (id, name, founder_id, description) VALUES (?, ?, ?, ?)",
    (company_id, name, founder_id, description),
)
```

**Best-Practice 偏离 (低风险, 3 处)**:

| 文件 | 位置 | 风险 | 说明 |
|------|------|------|------|
| `evidence_chain.py` | 6 处 f-string 拼接表名 | 低 | `TABLE` 和 `HEAD_TABLE` 是文件级常量, 非用户输入 |
| `governance/repository.py` | 1 处 f-string 拼接 WHERE 条件 | 低 | `where` 从硬编码条件列表中构建 |
| `web_ui.py` | 1 处 f-string 拼接列名 | 低 | `col` 仅从 3 个固定值的字典中获取 |

### 2.4 修复建议 (按优先级)

| 优先级 | 建议 | 工作量 | 影响 |
|--------|------|--------|------|
| HIGH | 无 (已安全) | — | — |
| MEDIUM | 重构 `evidence_chain.py`, 使用 `TABLE_MAP` 字典替代 f-string 表名拼接 | 小 | 消除不良编码模式扩散风险 |
| LOW | 考虑 ORM 迁移 (SQLAlchemy / Peewee) | 大 | 根除 SQL 注入风险, 提升可维护性 |
| LOW | 添加 pre-commit hook, 检查 `conn.execute()` 中非常量 f-string | 小 | 预防未来引入风险 |

### 2.5 详细审计报告

详见: [sql-injection-audit.md](sql-injection-audit.md)

---

## 3. Web UI 安全审计结果

### 3.1 审计范围

| 范围 | 内容 |
|------|------|
| 模板 | `gateway/templates/` 下 15 个 Jinja2 HTML 模板 |
| 后端 | `gateway/routers/web_ui.py` |
| 检查项目 | XSS (反射型/存储型), CSRF, 安全响应头 |

### 3.2 审计矩阵

| 安全向量 | 状态 | 风险等级 |
|----------|------|----------|
| XSS (反射型/存储型) | Jinja2 `{{ }}` 自动转义保护 | **低** |
| XSS 通过 `|safe` 过滤器 | 未在任何模板中使用 | **安全** |
| CSRF Token | 全部 5 个 POST 端点缺失 CSRF 验证 | **中** |
| Content-Security-Policy (CSP) | 缺失 | **低-中** |
| X-Frame-Options | 缺失 | **低** |
| X-Content-Type-Options | 缺失 | **低** |
| Strict-Transport-Security (HSTS) | 缺失 | **低** |
| Referrer-Policy | 缺失 | **低** |
| Permissions-Policy | 缺失 | **低** |

### 3.3 XSS 审计结论

**未发现可被利用的 XSS 漏洞**。Jinja2 的默认自动转义机制 (`{{ }}`) 保护了所有模板变量。关键发现:

- 15 个模板中无模板使用 `|safe` 过滤器
- 无模板使用 `{% autoescape false %}` 块
- `agent.name` 等用户输入字段即使包含 `<script>` 标签, 也会被转义为 `&lt;script&gt;`
- `login.html` 中的 `error` 变量自动转义, 但建议后端确认该变量不从用户输入直接拼接

### 3.4 CSRF 审计结论

**缺失 CSRF Token 验证 — 核心风险**。

影响范围 — 5 个 POST 端点无保护:

| 端点 | Form 模板 | 操作 |
|------|-----------|------|
| `POST /admin/companies/create` | `company_create.html` | 创建 Company |
| `POST /admin/proposals/new` | `proposal_new.html` | 创建 Proposal |
| `POST /admin/vote/{proposal_id}` | `vote.html` | 投票 |
| `POST /admin/dividends/publish` | `dividend_publish_form.html` | 发布分红 |
| `POST /admin/login` | `login.html` | 登录 |

**影响分析**: 攻击者可在第三方站点构造表单, 诱导已认证的 Admin 浏览器提交 POST 请求。由于会话认证基于 API Key (非 Cookie), 实际可利用性低于 Cookie 认证方案, 但仍需修复。

### 3.5 修复建议 (按优先级)

| 优先级 | 建议 | 说明 |
|--------|------|------|
| **HIGH** | **新增 CSRF Token 验证** | 对所有 POST 端点添加 CSRF 保护 |
| **HIGH** | **新增 Content-Security-Policy 头** | 限制脚本/样式来源 (当前从 CDN 加载 Bootstrap) |
| **HIGH** | **新增 X-Frame-Options: DENY 头** | 防止点击劫持 |
| **HIGH** | **新增 X-Content-Type-Options: nosniff 头** | 防止 MIME 类型嗅探 |
| MEDIUM | 新增 `Strict-Transport-Security` 头 | 强制 HTTPS |
| MEDIUM | 确认 `login.html` 的 `error` 变量不回显用户输入 | 防御性编码 |
| LOW | 新增 Referrer-Policy 和 Permissions-Policy 头 | 补充安全层 |
| LOW | 添加自动化 XSS 回归测试 | 确保转义机制持续有效 |

### 3.6 参考实现

**CSRF Token 实现示例**:

```python
from fastapi import Request, HTTPException
import secrets, hmac

def generate_csrf_token(request: Request) -> str:
    token = secrets.token_hex(32)
    request.session["csrf_token"] = token
    return token

def verify_csrf_token(request: Request, form_token: str) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not hmac.compare_digest(expected, form_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
```

**安全响应头中间件示例**:

```python
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src https://cdn.jsdelivr.net; "
            "form-action 'self'; "
            "base-uri 'self'; "
        )
        return response
```

### 3.7 详细审计报告

详见: [web-ui-security-audit.md](web-ui-security-audit.md)

---

## 4. 综合优先级矩阵

| 优先级 | 问题 | 影响面 | 工作量 | 建议完成时间 |
|--------|------|--------|--------|-------------|
| P0 (紧急) | 无 (SQL 注入已安全) | — | — | — |
| P1 (高) | CSRF Token 缺失 (5 个端点) | Web UI 所有 POST 操作 | 小 | 下一迭代 |
| P1 (高) | 安全响应头缺失 (CSP, X-Frame-Options 等) | Web UI 全局 | 小 | 下一迭代 |
| P2 (中) | `evidence_chain.py` f-string 表名拼接 | 代码一致性 | 小 | 下一个版本 |
| P3 (低) | 考虑 ORM 迁移 | 长期架构演进 | 大 | 中长期规划 |
| P3 (低) | 自动化安全回归测试 | 安全质量保障 | 中 | 下一个版本 |

---

## 5. 安全最佳实践 (开发指南)

### 5.1 SQL 安全

```python
# 推荐: 始终使用参数化查询
conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))

# 不推荐: 字符串拼接 (即使表名是常量)
conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (agent_id,))

# 推荐替代方案: TABLE_MAP 模式
TABLE_MAP = {
    "evidence": "evidence_entries",
    "chain_heads": "evidence_chain_heads",
}
conn.execute(f"SELECT * FROM {TABLE_MAP['evidence']} WHERE id = ?", (agent_id,))
```

### 5.2 XSS 防护

```jinja2
{# 安全: Jinja2 自动转义, 无需额外处理 #}
<div>{{ user_input }}</div>

{# 禁止: |safe 过滤器会关闭自动转义, 仅在确信 HTML 纯净时使用 #}
<div>{{ user_input | safe }}</div>

{# 推荐: 如需渲染 HTML, 使用 bleach 库清洗 #}
```

### 5.3 CSRF 防护

```html
<!-- 所有 POST 表单应包含 CSRF Token -->
<form method="POST" action="/admin/companies/create">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  ...
</form>
```

### 5.4 密钥管理

- 生产密钥使用密码管理器 (1Password / Vault) 生成和存储
- 开发/测试/生产使用不同的密钥
- 密钥轮换周期建议 90 天
- `.env` 文件权限设为 600, 禁止提交到 Git

### 5.5 CI/CD 安全

CI 中已配置安全扫描 (`.github/workflows/safety-scan.yml`):

- **pip-audit**: 依赖 CVE 扫描 (每次 push/PR)
- **gitleaks**: 密钥泄漏扫描 (每次 push/PR)

Gitleaks 配置: `.gitleaks.toml`

---

## 6. 安全相关文件索引

| 文件 | 说明 |
|------|------|
| [sql-injection-audit.md](sql-injection-audit.md) | SQL 注入审计详细报告 |
| [web-ui-security-audit.md](web-ui-security-audit.md) | Web UI (XSS/CSRF) 审计详细报告 |
| [.gitleaks.toml](../../.gitleaks.toml) | Gitleaks 密钥扫描规则 |
| [safety-scan.yml](../../.github/workflows/safety-scan.yml) | CI 安全扫描 Workflow |
| [配置参考](../ops/configuration.md) | 密钥等安全配置说明 |
| [生产检查清单](../ops/production-checklist.md) | 部署前安全检查项 |
| [运维手册](../ops/README.md) | 密钥管理和网络安全 |

---

## 7. 安全联系方式

- GitHub Issues (安全报告): https://github.com/wangxianjiangwxj-ctrl/agentmesh/issues
- 安全更新跟踪: 关注 GitHub Release Notes 中的安全修复说明
