#!/usr/bin/env python3
"""
AgentMesh Phase 21 — End-to-End Demo Script

Demonstrates the complete A2A agent workflow:

  1. Start AgentMeshBridge (5 agents auto-register)
  2. Register an agent via IdentityAgent (A2A register_agent action)
  3. Deposit points for the agent (EscrowAgent)
  4. Create a task (TaskMarketAgent)
  5. Hold escrow (EscrowAgent)
  6. Record evidence of creation (EvidenceAgent)
  7. Assign the task (TaskMarketAgent)
  8. Record evidence of assignment (EvidenceAgent)
  9. Deliver the task (TaskMarketAgent)
  10. Verify the task (TaskMarketAgent)
  11. Settle the task (TaskMarketAgent)
  12. Release escrow (EscrowAgent)
  13. Record settlement evidence (EvidenceAgent)
  14. Submit review (ReputationAgent)
  15. Query reputation (ReputationAgent)
  16. Verify evidence chain integrity (EvidenceAgent)
  17. Shutdown

Usage::

    PYTHONPATH=/path/to/agentmesh python scripts/e2e_demo.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap

# Ensure the agentmesh package is importable
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _print_step(num: int, title: str) -> None:
    """Print a formatted step header."""
    line = f" {num}. {title} "
    print()
    print("=" * 72)
    print(f"  STEP {line}")
    print("=" * 72)


def _print_result(label: str, data: object) -> None:
    """Print a structured result block."""
    if isinstance(data, dict):
        items = "\n    ".join(f"{k}: {v}" for k, v in data.items())
        print(f"  [{label}] -> {items}")
    elif isinstance(data, list):
        for item in data:
            print(f"  [{label}] -> {item}")
    else:
        print(f"  [{label}] -> {data}")


async def _run_demo() -> None:
    from agentmesh.agents.bridge import AgentMeshBridge

    # ── 1. Initialise Bridge ──────────────────────────────────────────
    _print_step(1, "Initialise AgentMeshBridge")
    bridge = AgentMeshBridge()
    bridge.start()
    print(f"        Bridge started. {bridge.registry.count()} agent(s) registered:")
    for info in bridge.registry.list_all():
        print(f"            - {info.agent_id}: capabilities={info.capabilities}")

    # ── 2. Register a new agent ────────────────────────────────────────
    _print_step(2, "Register a new agent via IdentityAgent")
    result = await bridge.send(
        "identity-service",
        "register_agent",
        {"name": "Alice", "auth_token": "alice-token"},
    )
    alice_id = result["agent_id"]
    _print_result("Alice agent registered", result)

    # ── 3. Register another agent (Bob, the executor) ──────────────────
    _print_step(3, "Register Bob (executor)")
    result = await bridge.send(
        "identity-service",
        "register_agent",
        {"name": "Bob", "auth_token": "bob-token"},
    )
    bob_id = result["agent_id"]
    _print_result("Bob agent registered", result)

    # ── 4. Deposit points for Alice ────────────────────────────────────
    _print_step(4, "Deposit points for Alice")
    result = await bridge.send(
        "escrow-service",
        "deposit",
        {"agent_id": alice_id, "amount": 500},
    )
    _print_result("Alice balance", result)

    # ── 5. Create a task ───────────────────────────────────────────────
    _print_step(5, "Create a task (Alice publishes)")
    result = await bridge.send(
        "task-market",
        "create_task",
        {
            "title": "Build a simple chatbot",
            "description": "Create a text-based chatbot for customer support",
            "escrow_amount": 100,
            "publisher_share": 0.3,
            "executor_share": 0.7,
            "publisher_id": alice_id,
            "signature": "demo-sig",
        },
    )
    task_id = result["task_id"]
    _print_result("Task created", result)

    # ── 6. Hold escrow ─────────────────────────────────────────────────
    _print_step(6, "Hold escrow for the task")
    result = await bridge.send(
        "escrow-service",
        "hold",
        {
            "agent_id": alice_id,
            "task_id": task_id,
            "amount": 100,
        },
    )
    _print_result("Escrow held", result)

    # ── 7. Record evidence (task created) ──────────────────────────────
    _print_step(7, "Record evidence of task creation")
    result = await bridge.send(
        "evidence-chain",
        "record_evidence",
        {
            "task_id": task_id,
            "action": "task.created",
            "actor_id": alice_id,
            "payload": {"title": "Build a simple chatbot"},
        },
    )
    _print_result("Evidence recorded", result)

    # ── 8. Assign task to Bob ──────────────────────────────────────────
    _print_step(8, "Assign task to Bob")
    result = await bridge.send(
        "task-market",
        "assign_task",
        {
            "task_id": task_id,
            "executor_id": bob_id,
            "signature": "demo-sig",
        },
    )
    _print_result("Task assigned", result)

    # ── 9. Record evidence (task assigned) ─────────────────────────────
    _print_step(9, "Record evidence of assignment")
    result = await bridge.send(
        "evidence-chain",
        "record_evidence",
        {
            "task_id": task_id,
            "action": "task.assigned",
            "actor_id": bob_id,
            "payload": {"executor_id": bob_id},
        },
    )
    _print_result("Evidence recorded", result)

    # ── 10. Deliver task ──────────────────────────────────────────────
    _print_step(10, "Bob delivers the task")
    result = await bridge.send(
        "task-market",
        "deliver_task",
        {
            "task_id": task_id,
            "delivery_url": "https://example.com/delivery/123",
            "executor_id": bob_id,
            "signature": "demo-sig",
        },
    )
    _print_result("Task delivered", result)

    # ── 11. Verify task ───────────────────────────────────────────────
    _print_step(11, "Alice verifies the task (approved)")
    result = await bridge.send(
        "task-market",
        "verify_task",
        {
            "task_id": task_id,
            "publisher_id": alice_id,
            "approved": True,
            "signature": "demo-sig",
        },
    )
    _print_result("Task verified", result)

    # ── 12. Settle task ───────────────────────────────────────────────
    _print_step(12, "Settle the task")
    result = await bridge.send(
        "task-market",
        "settle_task",
        {
            "task_id": task_id,
            "publisher_id": alice_id,
            "signature": "demo-sig",
        },
    )
    _print_result("Task settled", result)

    # ── 13. Release escrow ────────────────────────────────────────────
    _print_step(13, "Release escrow (Alice 30%, Bob 70%)")
    result = await bridge.send(
        "escrow-service",
        "release",
        {
            "task_id": task_id,
            "publisher_id": alice_id,
            "executor_id": bob_id,
            "escrow_amount": 100,
            "publisher_share": 0.3,
            "executor_share": 0.7,
        },
    )
    _print_result("Escrow released", result)

    # ── 14. Record evidence (settlement) ──────────────────────────────
    _print_step(14, "Record settlement evidence")
    result = await bridge.send(
        "evidence-chain",
        "record_evidence",
        {
            "task_id": task_id,
            "action": "task.settled",
            "actor_id": alice_id,
            "payload": {"status": "settled"},
            "secondary_actor_id": bob_id,
        },
    )
    _print_result("Settlement evidence", result)

    # ── 15. Submit review ─────────────────────────────────────────────
    _print_step(15, "Submit review (Alice rates Bob 5 stars)")
    result = await bridge.send(
        "reputation-service",
        "submit_review",
        {
            "task_id": task_id,
            "rater_id": alice_id,
            "target_id": bob_id,
            "score": 5,
            "comment": "Excellent work!",
        },
    )
    _print_result("Review submitted", result)

    # ── 16. Query reputation ──────────────────────────────────────────
    _print_step(16, "Query Bob's reputation")
    result = await bridge.send(
        "reputation-service",
        "get_reputation",
        {"agent_id": bob_id},
    )
    _print_result("Bob's reputation", result)

    # ── 17. Verify evidence chain ─────────────────────────────────────
    _print_step(17, "Verify evidence chain integrity")
    result = await bridge.send(
        "evidence-chain",
        "verify_chain",
        {"task_id": task_id},
    )
    _print_result("Evidence chain verification", result)

    # ── 18. List all agents ──────────────────────────────────────────
    _print_step(18, "List all registered agents (including bridge agents)")
    result = await bridge.send(
        "identity-service",
        "list_agents",
        {},
    )
    _print_result("Registered agents", result)

    # ── Summary ──────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("  DEMO COMPLETED SUCCESSFULLY")
    print("=" * 72)
    print()
    print(f"  Agents in registry: {bridge.registry.count()}")
    print(f"  Alice agent ID   : {alice_id}")
    print(f"  Bob agent ID     : {bob_id}")
    print(f"  Task ID          : {task_id}")
    print()

    # Cleanup
    bridge.shutdown()
    print("  Bridge shutdown. Goodbye.")


def main() -> None:
    asyncio.run(_run_demo())


if __name__ == "__main__":
    main()
