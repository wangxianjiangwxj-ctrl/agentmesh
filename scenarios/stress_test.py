#!/usr/bin/env python3
"""
AgentMesh Stress Test — Multi-Agent Economy Simulation

Stress-tests 10 agents through 5 complete task lifecycles using the
real platform economy modules (zero mock):

  - Identity:       Registration + key management (Ed25519)
  - Task Market:    Publish, bid, assign
  - Evidence Chain: Hash-linked, dual-signed lifecycle entries
  - Escrow:         Hold, release, split settlement
  - Audit Chain:    Hash-linked audit trail with double-signatures
  - Reputation:     Mutual reviews, Bayesian average computation

Usage:
    cd agentmesh/
    python3 scenarios/stress_test.py

Runs entirely locally with an in-memory SQLite database.
Zero network, zero external services required.
"""
from __future__ import annotations

import os
import random
import sys
import time

# ---------------------------------------------------------------------------
# sys.path setup — platform modules use bare imports (e.g. `from identity import`)
# so both project root and agentmesh/platform/ must be on sys.path.
# ---------------------------------------------------------------------------
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "agentmesh", "platform"))

from audit_chain import AuditChainService
from db_schema import create_test_db
from escrow import EscrowService
from evidence_chain import EvidenceChainService
from identity import IdentityService
from reputation import ReviewService

# ---------------------------------------------------------------------------
# Constants (defaults — used when no argument overrides are given)
# ---------------------------------------------------------------------------
AGENT_NAMES = [
    "Alice", "Bob", "Charlie", "Dave", "Eve",
    "Frank", "Grace", "Heidi", "Ivan", "Judy",
]

TASK_TITLES = [
    "Design logo for product launch",
    "Write technical documentation",
    "Refactor payment module",
    "Create marketing landing page",
    "Analyze user retention data",
]

TASK_REWARDS = [300, 500, 400, 600, 350]


# ---------------------------------------------------------------------------
# Dynamic generators — produce names / titles / rewards for any count
# ---------------------------------------------------------------------------
def generate_agent_names(count: int) -> list[str]:
    """Return ``count`` agent names, reusing defaults for the first 10."""
    names: list[str] = []
    for i in range(count):
        if i < len(AGENT_NAMES):
            names.append(AGENT_NAMES[i])
        else:
            names.append(f"Agent-{i+1:03d}")
    return names


def generate_task_titles(count: int) -> list[str]:
    """Return ``count`` task titles, reusing defaults for the first 5."""
    titles: list[str] = []
    for i in range(count):
        if i < len(TASK_TITLES):
            titles.append(TASK_TITLES[i])
        else:
            titles.append(f"Task #{i+1}: Automated workflow execution")
    return titles


def generate_task_rewards(count: int) -> list[int]:
    """Return ``count`` task rewards, reusing defaults for the first 5."""
    rewards: list[int] = []
    for i in range(count):
        if i < len(TASK_REWARDS):
            rewards.append(TASK_REWARDS[i])
        else:
            rewards.append(random.randint(200, 800))
    return rewards

# ---------------------------------------------------------------------------
# Formatting helpers (no emoji)
# ---------------------------------------------------------------------------
def ok(msg: str) -> None:
    print(f"  {msg}")


def info(msg: str) -> None:
    print(f"     {msg}")


def separator(title: str) -> None:
    print()
    print("=" * 66)
    print(f"  {title}")
    print("=" * 66)


# ---------------------------------------------------------------------------
# Core simulation — callable via CLI or as an imported function
# ---------------------------------------------------------------------------
def run_simulation(agent_count: int = 10, task_count: int = 5) -> int:
    """Run the multi-agent economy stress test.

    Args:
        agent_count: Number of agents to register (default 10).
        task_count:  Number of task lifecycles to execute (default 5).

    Returns:
        0 if all chain validations passed, 1 otherwise.
    """
    t_start = time.monotonic()

    # Dynamically generate names, titles, rewards based on requested counts
    agent_names = generate_agent_names(agent_count)
    task_titles = generate_task_titles(task_count)
    task_rewards_list = generate_task_rewards(task_count)

    print()
    print("  AgentMesh Stress Test — Multi-Agent Economy Simulation")
    print("  =======================================================")
    print(f"  Agents: {agent_count}  |  Tasks: {task_count}")
    print()

    # ---- Setup: in-memory test database --------------------------------

    conn, db_path = create_test_db()

    identity = IdentityService(db_path)
    # Share the connection so all services see the same in-memory state
    identity._conn = conn

    evidence = EvidenceChainService(identity, conn)
    escrow = EscrowService(conn, identity)
    reviews = ReviewService(conn, identity, evidence)
    audit = AuditChainService(identity, conn)

    # ---- Step 1: Register agents ------------------------------------

    separator("Step 1: Register Agents")

    agents: dict[str, dict] = {}
    for name in agent_names:
        agent = identity.register(name, auth_token=f"token_{name.lower()}")
        agents[name] = agent
        ok(f"[OK] {name} (did:{agent['did'][:32]}...) registered")

    ok(f"Total: {len(agents)} agents registered")

    # Ensure escrow accounts with initial balance for all agents
    for name in agent_names:
        escrow.ensure_account(agents[name]["agent_id"])

    # ---- Step 2: Execute task lifecycles -----------------------------

    task_count_txt = f"Step 2: Task Lifecycles ({task_count} tasks)"
    separator(task_count_txt)

    total_evidence         = 0
    total_evidence_valid   = 0
    total_audit_entries    = 0
    total_audit_valid      = 0
    total_escrow_held      = 0
    total_escrow_released  = 0
    total_reviews          = 0
    total_ratings          = []

    for task_idx in range(task_count):
        # --- Role assignment ---------------------------------------
        # Publishers: first half of agents; Executors: second half
        # If there are fewer than 2 agents, both roles use the same pool
        half = max(1, agent_count // 2)
        publisher_name = agent_names[task_idx % half]
        executor_name  = agent_names[(half + task_idx) % agent_count]
        # Ensure publisher and executor are different
        if publisher_name == executor_name:
            executor_name = agent_names[(half + task_idx + 1) % agent_count]
        publisher      = agents[publisher_name]
        executor       = agents[executor_name]

        task_id = f"stress-task-{task_idx + 1:03d}"
        title   = task_titles[task_idx]
        reward  = task_rewards_list[task_idx]

        # Random split: publisher keeps 30-70%, executor gets the rest
        pub_share = round(random.uniform(0.30, 0.70), 2)
        exe_share = round(1.0 - pub_share, 2)

        # --- a) Publish task ---------------------------------------
        with conn:
            conn.execute(
                """INSERT INTO tasks
                   (id, publisher_id, title, description, escrow_amount, status,
                    executor_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'open', NULL, datetime('now'), datetime('now'))""",
                (task_id, publisher["agent_id"], title,
                 f"Task #{task_idx+1} description", reward),
            )
        info(f"Task-{task_idx+1:03d}: {title} ({reward} pts, "
             f"split {pub_share:.0%}/{exe_share:.0%})")

        # --- b) Escrow hold ----------------------------------------
        escrow.hold(publisher["agent_id"], task_id, reward)
        total_escrow_held += reward

        # --- c) Evidence: publish ----------------------------------
        evidence.record(task_id, "publish", publisher["agent_id"],
                        {"title": title, "reward": reward})
        total_evidence += 1

        # --- d) Assign executor + evidence -------------------------
        with conn:
            conn.execute(
                """UPDATE tasks
                   SET status='assigned', executor_id=?, updated_at=datetime('now')
                   WHERE id=?""",
                (executor["agent_id"], task_id),
            )
        evidence.record(task_id, "assign", publisher["agent_id"],
                        {"executor": executor_name},
                        secondary_actor_id=executor["agent_id"])
        total_evidence += 1

        # --- e) Deliver + evidence ---------------------------------
        with conn:
            conn.execute(
                """UPDATE tasks
                   SET status='delivered', updated_at=datetime('now')
                   WHERE id=?""",
                (task_id,),
            )
        evidence.record(task_id, "deliver", executor["agent_id"],
                        {"delivery_url": f"file://result-{task_id}.md"},
                        secondary_actor_id=publisher["agent_id"])
        total_evidence += 1

        # --- f) Verify + evidence ----------------------------------
        rating = random.randint(3, 5)
        with conn:
            conn.execute(
                """UPDATE tasks
                   SET status='verified', updated_at=datetime('now')
                   WHERE id=?""",
                (task_id,),
            )
        evidence.record(task_id, "verify", publisher["agent_id"],
                        {"status": "approved", "rating": rating})
        total_evidence += 1

        # --- g) Escrow release -------------------------------------
        result = escrow.release(task_id, publisher["agent_id"],
                                executor["agent_id"], reward,
                                pub_share, exe_share)
        total_escrow_released += result["executor_reward"]
        with conn:
            conn.execute(
                """UPDATE tasks
                   SET status='settled', updated_at=datetime('now')
                   WHERE id=?""",
                (task_id,),
            )

        # --- h) Evidence: settle -----------------------------------
        evidence.record(task_id, "settle", publisher["agent_id"],
                        {"publisher_return": result["publisher_return"],
                         "executor_reward": result["executor_reward"]})
        total_evidence += 1

        # --- i) Verify evidence chain integrity --------------------
        ev_chain   = evidence.verify_chain(task_id)
        ev_valid   = sum(1 for e in ev_chain if e["chain_ok"])
        total_evidence_valid += ev_valid

        # --- j) Audit chain: record all lifecycle events -----------
        audit.record(task_id, "publish", publisher["agent_id"],
                     {"title": title, "reward": reward})
        audit.record(task_id, "assign", publisher["agent_id"],
                     {"executor": executor_name},
                     receiver_id=executor["agent_id"])
        audit.record(task_id, "deliver", executor["agent_id"],
                     {"delivery_url": f"file://result-{task_id}.md"},
                     receiver_id=publisher["agent_id"])
        audit.record(task_id, "verify", publisher["agent_id"],
                     {"status": "approved", "rating": rating},
                     receiver_id=executor["agent_id"])
        audit.record(task_id, "settle", publisher["agent_id"],
                     {"publisher_return": result["publisher_return"],
                      "executor_reward": result["executor_reward"]})

        # --- k) Verify audit chain integrity -----------------------
        au_chain    = audit.verify_chain(task_id)
        au_valid    = sum(1 for a in au_chain if a["chain_ok"])
        total_audit_entries += len(au_chain)
        total_audit_valid   += au_valid

        # --- l) Reputation: mutual reviews -------------------------
        reviews.on_task_settled(task_id,
                                publisher["agent_id"], executor["agent_id"])

        pub_rating = random.randint(3, 5)
        exe_rating = random.randint(3, 5)
        reviews.submit_review(task_id, publisher["agent_id"],
                              executor["agent_id"], pub_rating,
                              f"Good work by {executor_name}")
        reviews.submit_review(task_id, executor["agent_id"],
                              publisher["agent_id"], exe_rating,
                              f"Good task by {publisher_name}")
        total_ratings.extend([pub_rating, exe_rating])
        total_reviews += 2

        # --- m) Result line ----------------------------------------
        ev_all_ok = ev_valid == len(ev_chain)
        au_all_ok = au_valid == len(au_chain)
        chain_tag = "valid" if (ev_all_ok and au_all_ok) else "INVALID"
        ok(f"[OK] Task-{task_idx+1:03d}: "
           f"publish->assign->deliver->verify->settle "
           f"[chain: {chain_tag}]")

    # ---- Step 3: Reputation summary -----------------------------------

    separator("Step 3: Reputation Summary")

    all_reputations: dict[str, dict] = {}
    for name, agent in agents.items():
        rep = reviews.get_reputation(agent["agent_id"])
        all_reputations[name] = rep
        if rep["total_reviews"] > 0:
            ok(f"[OK] {name}: {rep['avg_rating']:.1f}/5.0 "
               f"({rep['total_reviews']} reviews)")
        else:
            ok(f"[--] {name}: no reviews yet")

    # Weighted average across all agents that have been reviewed
    rated_agents = {
        n: all_reputations[n]
        for n in all_reputations
        if all_reputations[n]["total_reviews"] > 0
    }
    avg_rating_all = (
        sum(r["avg_rating"] for r in rated_agents.values()) /
        max(1, len(rated_agents))
    )

    # ---- Summary -------------------------------------------------------

    duration = time.monotonic() - t_start

    print()
    print("  " + "=" * 66)
    print("  Stress Test Summary")
    print("  " + "=" * 66)
    print(f"  Agents:     {len(agents)} registered")
    print(f"  Tasks:      {task_count} published, {task_count} completed")
    print(f"  Escrow:     total held {total_escrow_held}, "
          f"released {total_escrow_released}")
    print(f"  Evidence:   {total_evidence} entries, "
          f"{total_evidence_valid}/{total_evidence} chain valid")
    print(f"  Audits:     {total_audit_entries} entries, "
          f"{total_audit_valid}/{total_audit_entries} chain valid")
    print(f"  Reputation: {len(rated_agents)} agents rated, "
          f"avg {avg_rating_all:.1f}/5.0")
    print(f"  Duration:   {duration:.2f}s")
    print()

    # ---- Cleanup -------------------------------------------------------

    identity.close()
    conn.close()
    os.unlink(db_path)

    # Return 0 on success, 1 if any chain validation failed
    all_chains_valid = (
        total_evidence_valid == total_evidence
        and total_audit_valid == total_audit_entries
    )
    return 0 if all_chains_valid else 1


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def main() -> int:
    """Run the stress test with default parameters."""
    return run_simulation()


if __name__ == "__main__":
    sys.exit(main())
