# SQL Injection Audit Report

**Date**: 2026-06-09
**Scope**: `agentmesh/platform/` -- all `.py` files
**Methodology**: Grep for `conn.execute()`, `cursor.execute()` and examine SQL construction patterns (f-strings, string concatenation, `.format()`, `%` formatting).

---

## Summary

| Metric | Value |
|--------|-------|
| Files scanned | 22 |
| SQL execution sites reviewed | ~120 |
| Confirmed SQL injection vulnerabilities | 0 |
| Best-practice deviations (low risk) | 3 |
| Risk level | **Low** |

---

## Methodology

Each SQL execution site (`conn.execute()`) was classified into one of:

- **Parameterized (safe)**: Values passed as `?` / `%s` placeholders via the second argument.
- **Constant f-string (safe)**: f-string contains only hardcoded table/column names (class-level constants or fixed dict values), with user values parameterized.
- **Concatenated with user input (HIGH RISK)**: User-controlled values directly concatenated into SQL text.

---

## Detailed Findings

### Parameterized Queries (Safe) -- Representative Examples

All `conn.execute()` calls across the codebase use parameterized placeholders (`?`) for user-supplied values. For example:

```python
# agentmesh/platform/identity/__init__.py
row = self.conn.execute(
    "SELECT * FROM agents WHERE id = ?", (agent_id,)
).fetchone()

# agentmesh/platform/gateway/routers/web_ui.py
db.execute(
    "INSERT INTO companies (id, name, founder_id, description) VALUES (?, ?, ?, ?)",
    (company_id, name, founder_id, description),
)

# agentmesh/platform/dividend.py
records = self.conn.execute(query, params).fetchall()
```

### F-string with Constants (Low Risk) -- 3 Sites

The following use f-strings for table names that are class-level constants, **not user input**. User values are still parameterized. These are **not exploitable** but are flagged as a best-practice deviation:

**File**: `agentmesh/platform/evidence_chain.py`
- Line 141: `f"""SELECT * FROM {TABLE} WHERE task_id = ? ORDER BY chain_index ASC"""`
- Line 187: `f"""SELECT * FROM {TABLE} WHERE task_id = ? ORDER BY chain_index ASC"""`
- Line 223: `f"SELECT latest_hash as h, latest_index as idx FROM {HEAD_TABLE} WHERE task_id = ?"`
- Line 352: `f"""INSERT INTO {TABLE} (id, task_id, ...) VALUES (?, ?, ...)"""`
- Line 362: `f"""INSERT OR REPLACE INTO {HEAD_TABLE} (task_id, ...) VALUES (?, ?, ...)"""`
- Line 380: `f"SELECT * FROM {TABLE} WHERE id = ?"`

**Risk**: `TABLE` and `HEAD_TABLE` are hardcoded string constants at the top of the file (`TABLE = "evidence_entries"`, `HEAD_TABLE = "evidence_chain_heads"`). Not controllable by any user. Low risk, but would be safer with a mapping approach.

**File**: `agentmesh/platform/governance/repository.py`
- Line 164: `f"SELECT * FROM proposals{where} ORDER BY created_at DESC"`

**Risk**: `where` is built from conditions like `"company_id = ?"` and `"status = ?"` with actual values passed as parameters. The conditions list only contains hardcoded strings. Not exploitable.

**File**: `agentmesh/platform/gateway/routers/web_ui.py`
- Line 632: `f"UPDATE proposals SET {col} = {col} + 1 WHERE id = ?"`

**Risk**: `col` comes from a hardcoded dictionary `col_map = {'approve': 'votes_for', 'reject': 'votes_against', 'abstain': 'votes_abstain'}`. Only 3 fixed column names are possible. Not exploitable.

### String Concatenation (Safe Pattern)

**File**: `agentmesh/platform/dividend.py`
- Line 199-203: `query += " AND company_id = ?"` -- uses parameterized value; no concatenation of user data. Safe.

---

## Recommendations

1. **Refactor evidence_chain.py** to use a `TABLE_MAP` dict or ORM-like approach instead of string interpolation for table names. While the current constants are safe, it sets a precedent that could be copied unsafely.
2. **Use an ORM** (SQLAlchemy, PonyORM, or Peewee) instead of raw SQL for new development to eliminate SQL injection risk entirely.
3. **Add a pre-commit hook** using `ruff` or a custom grep to flag any `conn.execute()` with f-strings containing non-constant interpolations.
4. **Run gitleaks** (already configured in `.gitleaks.toml`) on each PR to catch any accidentally committed injection payloads or secrets.

---

## Conclusion

The AgentMesh platform codebase demonstrates **good SQL injection hygiene**. All user-supplied values are passed through parameterized queries (`?` placeholders). The few f-string usages involve only hardcoded constants and present no exploitable risk. No remediation is urgently required.
