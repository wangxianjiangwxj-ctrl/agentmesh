"""
AgentMesh Phase 19 Day 2 — 集成测试

验证全套 5 模块端到端协作（sync, SQLite-backed）。

运行:
    cd <this-dir> && python -m pytest test_integration_day2.py -v
"""
from __future__ import annotations

import tempfile
import uuid
import os
from pathlib import Path

import pytest

from db_schema import init_db
from identity import IdentityService
from evidence_chain import EvidenceChainService
from escrow import EscrowService
from reputation import ReviewService

# ─── 共享 Fixture ─────────────────────────────────────

@pytest.fixture
def svc():
    """初始化全部 5 模块 + 2 个测试 agent"""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db_path = f.name

    conn = init_db(db_path)

    identity = IdentityService(db_path)
    identity._conn = conn

    evidence = EvidenceChainService(identity, conn)
    escrow = EscrowService(conn, identity)
    reviews = ReviewService(conn, identity, evidence)

    alice = identity.register("Alice")
    bob = identity.register("Bob")

    # 预存余额
    for aid in (alice["agent_id"], bob["agent_id"]):
        conn.execute("INSERT OR IGNORE INTO accounts (agent_id, balance, frozen) VALUES (?, 2000, 0)", (aid,))
    conn.commit()

    yield {
        "conn": conn,
        "db_path": db_path,
        "identity": identity,
        "evidence": evidence,
        "escrow": escrow,
        "reviews": reviews,
        "alice": alice,
        "bob": bob,
    }

    identity.close()
    conn.close()
    Path(db_path).unlink(missing_ok=True)


# ─── 工具函数 ──────────────────────────────────────────

def _create_task(conn, publisher_id, title="默认任务", amount=500):
    """创建 open 状态的任务"""
    task_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO tasks (id, publisher_id, title, description, escrow_amount, status) VALUES (?, ?, ?, ?, ?, 'open')",
        (task_id, publisher_id, title, "集成测试", amount),
    )
    conn.commit()
    return task_id


# ─── 测试用例 ──────────────────────────────────────────

def test_tc01_register_and_create_task(svc):
    """TC-01: 身份注册 + 任务创建"""
    alice = svc["alice"]
    bob = svc["bob"]
    conn = svc["conn"]

    a_info = svc["identity"].get_agent(alice["agent_id"])
    assert a_info["name"] == "Alice"
    b_info = svc["identity"].get_agent(bob["agent_id"])
    assert b_info["name"] == "Bob"

    task_id = _create_task(conn, alice["agent_id"], "TC-01测试", 300)
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "open"
    assert task["escrow_amount"] == 300

    print(f"[TC-01] ✅ {alice['agent_id'][:8]} / {bob['agent_id'][:8]} / task={task_id[:8]}")


def test_tc02_escrow_hold_release(svc):
    """TC-02: Escrow 冻结 + 释放"""
    conn = svc["conn"]
    escrow = svc["escrow"]
    alice = svc["alice"]
    bob = svc["bob"]
    task_id = _create_task(conn, alice["agent_id"], "Escrow测试", 500)

    # Hold — 冻结 publisher 资金
    acct = escrow.hold(alice["agent_id"], task_id, 500)
    assert acct["frozen"] >= 500

    # Release — 释放给 executor
    result = escrow.release(task_id, alice["agent_id"], bob["agent_id"], 500, 0.1, 0.9)
    assert result["executor_reward"] >= 450  # 90% of 500
    assert result["publisher_return"] <= 50   # 10% of 500

    bob_acct = svc["identity"].get_agent(bob["agent_id"])
    print(f"[TC-02] ✅ hold+release OK")


def test_tc03_review_and_reputation(svc):
    """TC-03: 评价 + 信誉分更新"""
    conn = svc["conn"]
    reviews = svc["reviews"]
    alice = svc["alice"]
    bob = svc["bob"]
    task_id = _create_task(conn, alice["agent_id"], "评价测试", 100)

    conn.execute("UPDATE tasks SET status='settled' WHERE id=?", (task_id,))
    conn.commit()

    reviews.on_task_settled(task_id, alice["agent_id"], bob["agent_id"])
    reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 5, "Excellent!")

    rep = reviews.get_reputation(bob["agent_id"])
    assert rep["total_reviews"] >= 1
    assert 3.0 < rep["avg_rating"] <= 5.0
    assert rep["as_executor"] >= 1

    print(f"[TC-03] ✅ bob rep: avg={rep['avg_rating']:.2f} n={rep['total_reviews']}")


def test_tc04_evidence_chain_logging(svc):
    """TC-04: 证据链记录"""
    conn = svc["conn"]
    evidence = svc["evidence"]
    alice = svc["alice"]
    bob = svc["bob"]
    task_id = _create_task(conn, alice["agent_id"], "证据链测试", 200)

    for action, actor in [("task_created", alice["agent_id"]),
                          ("task_assigned", bob["agent_id"]),
                          ("task_delivered", bob["agent_id"])]:
        entry = evidence.record(task_id, action, actor, {"task_id": task_id})
        assert entry.action == action

    entries = evidence.get_by_task(task_id)
    assert len(entries) == 3
    assert entries[0]["chain_index"] == 1
    assert entries[-1]["chain_index"] == 3

    print(f"[TC-04] ✅ chain: {len(entries)} entries")


def test_tc05_schema_integrity(svc):
    """TC-05: 9 表字段完整性"""
    conn = svc["conn"]
    expected = {
        "agents": ["id", "did", "name", "public_key", "created_at", "updated_at"],
        "tasks": ["id", "publisher_id", "title", "status", "escrow_amount", "created_at"],
        "task_bids": ["id", "task_id", "bidder_id", "bid_amount", "status", "created_at"],
        "evidence_chain": ["id", "task_id", "chain_index", "action", "actor_id", "signature", "chain_hash", "created_at"],
        "accounts": ["agent_id", "balance", "frozen", "updated_at"],
        "transactions": ["id", "task_id", "from_agent", "to_agent", "amount", "action", "status", "created_at"],
        "reviews": ["id", "task_id", "reviewer_id", "target_id", "rating", "comment", "created_at"],
        "agent_reputation": ["agent_id", "avg_rating", "total_reviews", "as_publisher", "as_executor", "updated_at"],
        "revenue_shares": ["id", "task_id", "agent_id", "share_pct", "role", "created_at"],
    }

    table_names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for tbl, cols in expected.items():
        assert tbl in table_names, f"Missing table: {tbl}"
        actual = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
        for c in cols:
            assert c in actual, f"{tbl} missing col: {c}"

    assert len(table_names & set(expected)) == 9
    print(f"[TC-05] ✅ 9 tables, all columns verified")


def test_tc06_full_e2e_lifecycle(svc):
    """TC-06: 端到端 — 注册→出价→分配→冻结→交付→验收→释放→评价→信誉→证据链"""
    conn = svc["conn"]
    evidence = svc["evidence"]
    escrow = svc["escrow"]
    reviews = svc["reviews"]
    alice = svc["alice"]
    bob = svc["bob"]

    # Step 1: 创建任务
    task_id = _create_task(conn, alice["agent_id"], "端到端测试", 1000)
    evidence.record(task_id, "task_created", alice["agent_id"], {"task_id": task_id})
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()["status"] == "open"

    # Step 2: 出价 + 接受
    bid_id = uuid.uuid4().hex
    conn.execute("INSERT INTO task_bids (id, task_id, bidder_id, bid_amount, status) VALUES (?, ?, ?, 800, 'accepted')",
                 (bid_id, task_id, bob["agent_id"]))
    conn.commit()

    # Step 3: 分配
    conn.execute("UPDATE tasks SET status='assigned', executor_id=? WHERE id=?", (bob["agent_id"], task_id))
    conn.commit()
    evidence.record(task_id, "task_assigned", bob["agent_id"], {"task_id": task_id})
    assert conn.execute("SELECT executor_id FROM tasks WHERE id=?", (task_id,)).fetchone()["executor_id"] == bob["agent_id"]

    # Step 4: Escrow 冻结
    escrow.hold(alice["agent_id"], task_id, 1000)
    alice_acct = conn.execute("SELECT * FROM accounts WHERE agent_id=?", (alice["agent_id"],)).fetchone()
    assert alice_acct["frozen"] >= 1000

    # Step 5: 交付
    conn.execute("UPDATE tasks SET status='delivered', delivery_url=?, delivery_hash=? WHERE id=?",
                 ("https://ex.com/output.zip", "sha256:abc", task_id))
    conn.commit()
    evidence.record(task_id, "task_delivered", bob["agent_id"], {"url": "https://ex.com/output.zip"})

    # Step 6: 验收
    conn.execute("UPDATE tasks SET status='verified' WHERE id=?", (task_id,))
    conn.commit()

    # Step 7: Escrow 释放 (90% to executor)
    release = escrow.release(task_id, alice["agent_id"], bob["agent_id"], 1000, 0.1, 0.9)
    assert release["executor_reward"] >= 900

    # Step 8: 结算
    conn.execute("UPDATE tasks SET status='settled' WHERE id=?", (task_id,))
    conn.commit()
    reviews.on_task_settled(task_id, alice["agent_id"], bob["agent_id"])

    # Step 9: 评价
    reviews.submit_review(task_id, alice["agent_id"], bob["agent_id"], 5, "完美交付")
    rep_bob = reviews.get_reputation(bob["agent_id"])
    assert rep_bob["total_reviews"] >= 1
    assert rep_bob["as_executor"] >= 1

    # Step 10: 证据链完整性
    entries = evidence.get_by_task(task_id)
    assert len(entries) >= 3

    print(f"[TC-06] ✅ E2E | task={task_id[:8]} | escrow=1000 | rep={rep_bob['avg_rating']:.2f} | chain={len(entries)}")
