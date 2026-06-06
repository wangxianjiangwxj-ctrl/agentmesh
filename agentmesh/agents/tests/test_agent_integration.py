"""Integration tests for A2A Agent wrappers (Phase 20 Direction C).

Uses asyncio.run() for each test so no pytest-asyncio dependency needed.
"""
from __future__ import annotations

import asyncio
import uuid
import time
from pathlib import Path
import tempfile
import sqlite3

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agents import (
    A2AMessage, AgentInfo, AgentRegistry,
    IdentityAgent, TaskMarketAgent, EscrowAgent,
    EvidenceAgent, ReputationAgent,
)
from identity import IdentityService
from db_schema import init_db
from escrow import EscrowService
from evidence_chain import EvidenceChainService
from reputation import ReviewService
from task_market_api import TaskMarketService, InMemoryTaskRepository, MockSignatureVerifier


def _msg(src, tgt, action, payload):
    return A2AMessage(
        source_agent_id=src,
        target_agent_id=tgt,
        action=action,
        payload=payload,
        message_id=uuid.uuid4().hex,
        timestamp=time.time(),
    )


def _full_db() -> tuple[sqlite3.Connection, Path]:
    path = Path(tempfile.mktemp(suffix=".db"))
    conn = init_db(str(path))
    conn.row_factory = sqlite3.Row
    return conn, path


# =======================================================================
# IdentityAgent tests
# =======================================================================


def test_register_agent():
    conn, path = _full_db()
    try:
        reg = AgentRegistry()
        ia = IdentityAgent(IdentityService(path), reg)

        async def run():
            return await ia.handle_message(_msg(
                "caller", "identity", "register_agent", {"name": "agent-1", "auth_token": ""}
            ))

        resp = asyncio.run(run())
        assert resp.action == "ok", f"Expected ok, got {resp.action}: {resp.payload}"
        assert resp.payload.get("did", "").startswith("did:agentmesh:")
        assert len(resp.payload["agent_id"]) > 0
        # Registry must have the agent
        assert reg.count() >= 1
    finally:
        conn.close()
        path.unlink()
    print("  PASS test_register_agent")


def test_get_agent():
    conn, path = _full_db()
    try:
        reg = AgentRegistry()
        ia = IdentityAgent(IdentityService(path), reg)

        async def run():
            r1 = await ia.handle_message(_msg("c", "i", "register_agent", {"name": "a1", "auth_token": ""}))
            aid = r1.payload["agent_id"]
            r2 = await ia.handle_message(_msg("c", "i", "get_agent", {"agent_id": aid}))
            return r2

        resp = asyncio.run(run())
        assert resp.action == "ok", f"Expected ok, got {resp.action}: {resp.payload}"
        assert resp.payload["name"] == "a1"
    finally:
        conn.close()
        path.unlink()
    print("  PASS test_get_agent")


def test_get_agent_not_found():
    conn, path = _full_db()
    try:
        ia = IdentityAgent(IdentityService(path), AgentRegistry())

        async def run():
            return await ia.handle_message(_msg("c", "i", "get_agent", {"agent_id": "nonexistent"}))

        resp = asyncio.run(run())
        assert resp.action == "error"
    finally:
        conn.close()
        path.unlink()
    print("  PASS test_get_agent_not_found")


def test_list_agents():
    conn, path = _full_db()
    try:
        reg = AgentRegistry()
        ia = IdentityAgent(IdentityService(path), reg)

        async def run():
            await ia.handle_message(_msg("c", "i", "register_agent", {"name": "a1", "auth_token": ""}))
            await ia.handle_message(_msg("c", "i", "register_agent", {"name": "a2", "auth_token": ""}))
            return await ia.handle_message(_msg("c", "i", "list_agents", {}))

        resp = asyncio.run(run())
        assert resp.action == "ok"
        assert isinstance(resp.payload["agents"], list)
        assert resp.payload["total"] == 2
    finally:
        conn.close()
        path.unlink()
    print("  PASS test_list_agents")


def test_unknown_action_identity():
    conn, path = _full_db()
    try:
        ia = IdentityAgent(IdentityService(path), AgentRegistry())

        async def run():
            return await ia.handle_message(_msg("c", "i", "nonexistent", {}))

        resp = asyncio.run(run())
        assert resp.action == "error"
    finally:
        conn.close()
        path.unlink()
    print("  PASS test_unknown_action_identity")


# =======================================================================
# TaskMarketAgent tests
# =======================================================================


def test_task_create_and_list():
    reg = AgentRegistry()
    ta = TaskMarketAgent(TaskMarketService(InMemoryTaskRepository(), MockSignatureVerifier()), reg)

    async def run():
        r1 = await ta.handle_message(_msg("pub", "m", "create_task", {
            "title": "Test task", "description": "A test task",
            "escrow_amount": 100, "publisher_share": 0.9, "executor_share": 0.1,
            "publisher_id": "pub-1",
        }))
        assert r1.action == "ok", f"create_task failed: {r1.payload}"
        task_id = r1.payload["task_id"]
        assert task_id

        r2 = await ta.handle_message(_msg("c", "m", "list_tasks", {}))
        assert r2.action == "ok"
        assert isinstance(r2.payload["tasks"], list)
        assert r2.payload["total"] >= 1
    print("  PASS test_task_create_and_list")


def test_task_unknown_action():
    reg = AgentRegistry()
    ta = TaskMarketAgent(TaskMarketService(InMemoryTaskRepository(), MockSignatureVerifier()), reg)

    async def run():
        return await ta.handle_message(_msg("c", "m", "bad_action", {}))

    resp = asyncio.run(run())
    assert resp.action == "error"
    print("  PASS test_task_unknown_action")


# =======================================================================
# EscrowAgent tests
# =======================================================================


def test_escrow_deposit():
    conn, path = _full_db()
    try:
        reg = AgentRegistry()
        isvc = IdentityService(path)
        ia = IdentityAgent(isvc, reg)
        ea = EscrowAgent(EscrowService(conn, isvc), reg)

        async def run():
            r1 = await ia.handle_message(_msg("c", "i", "register_agent", {"name": "ea", "auth_token": ""}))
            agent_id = r1.payload["agent_id"]
            r2 = await ea.handle_message(_msg("c", "e", "deposit", {"agent_id": agent_id, "amount": 500}))
            return r2

        resp = asyncio.run(run())
        assert resp.action == "ok", f"deposit failed: {resp.payload}"
        assert resp.payload["balance"] >= 500
    finally:
        conn.close()
        path.unlink()
    print("  PASS test_escrow_deposit")


# =======================================================================
# EvidenceAgent tests
# =======================================================================


def test_evidence_record_and_query():
    conn, path = _full_db()
    try:
        reg = AgentRegistry()
        isvc = IdentityService(path)
        esvc = EvidenceChainService(isvc, conn)
        eva = EvidenceAgent(esvc, reg)

        async def run():
            r1 = await eva.handle_message(_msg("a", "e", "record_evidence", {
                "task_id": "t1", "actor_id": "agent-a", "action": "deliver",
                "payload": {"result": "success"}
            }))
            assert r1.action == "ok", f"record failed: {r1.payload}"
            r2 = await eva.handle_message(_msg("c", "e", "get_evidence_chain", {"task_id": "t1"}))
            assert r2.action == "ok"
            assert isinstance(r2.payload["entries"], list)
            assert len(r2.payload["entries"]) >= 1
    finally:
        conn.close()
        path.unlink()
    print("  PASS test_evidence_record_and_query")


# =======================================================================
# ReputationAgent tests
# =======================================================================


def test_reputation_submit_and_query():
    conn, path = _full_db()
    try:
        reg = AgentRegistry()
        isvc = IdentityService(path)
        esvc = EvidenceChainService(isvc, conn)
        ra = ReputationAgent(ReviewService(conn, isvc, esvc), reg)

        async def run():
            r1 = await ra.handle_message(_msg("c", "r", "submit_review", {
                "task_id": "t1", "rater_id": "a", "target_id": "b",
                "score": 5, "comment": "good"
            }))
            assert r1.action == "ok", f"submit_review failed: {r1.payload}"
            r2 = await ra.handle_message(_msg("c", "r", "get_reputation", {"agent_id": "b"}))
            assert r2.action == "ok"
            assert r2.payload["reputation"]["rating_count"] >= 1
    finally:
        conn.close()
        path.unlink()
    print("  PASS test_reputation_submit_and_query")


# =======================================================================
# Runner
# =======================================================================


if __name__ == "__main__":
    print("=== Phase 20 Direction C — Agent Integration Tests ===\n")
    test_register_agent()
    test_get_agent()
    test_get_agent_not_found()
    test_list_agents()
    test_unknown_action_identity()
    test_task_create_and_list()
    test_task_unknown_action()
    test_escrow_deposit()
    test_evidence_record_and_query()
    test_reputation_submit_and_query()
    print("\n=== All 10 tests passed ===")
