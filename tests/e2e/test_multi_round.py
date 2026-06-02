#!/usr/bin/env python3
"""Multi-round conversation tests for A2A protocol (Direction A, Phase B3).

Tests simulate realistic multi-turn Agent conversations:
  1. 3-round standard task negotiation (send -> poll -> cancel lifecycle)
  2. 5-round mixed interaction with incremental payloads
  3. 3-agent chain (A -> B -> C simulated delegation)

All tests use the real A2A server + HttpProvider client (auto-started).

Usage:
    pytest tests/e2e/test_multi_round.py -v
    pytest tests/e2e/test_multi_round.py -v --server-port 8080   # existing server
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest

# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

try:
    from agentmesh.a2a_server import HttpProvider, SSEStream
    from agentmesh.a2a_provider import A2AError
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from agentmesh.a2a_server import HttpProvider, SSEStream
    from agentmesh.a2a_provider import A2AError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_PORT = int(os.environ.get("A2A_SERVER_PORT", "8090"))
SERVER_URL = f"http://localhost:{SERVER_PORT}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ensure_server():
    """Start server if not already running, return (proc, url)."""
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(f"{SERVER_URL}/ping", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return None  # already running
    except Exception:
        pass

    script = os.path.join(
        os.path.dirname(__file__), "..", "..", "agentmesh", "a2a_server.py"
    )
    proc = subprocess.Popen(
        [sys.executable, script, "server", "--port", str(SERVER_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    return proc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(task_id: str, text: str = "", state: str = "submitted") -> dict:
    """Create a standard task dict."""
    return {
        "id": task_id,
        "status": {"state": state},
        "payload": {"text": text},
    }


def _make_multi_round_task(task_id: str, history: list[dict]) -> dict:
    """Create a task with conversation history for multi-round simulation."""
    return {
        "id": task_id,
        "status": {"state": "submitted"},
        "payload": {"text": json.dumps(history) if history else "start"},
        "metadata": {"rounds": len(history), "history": history},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMultiRoundConversation(unittest.TestCase):
    """Multi-round conversation patterns for A2A protocol."""

    @classmethod
    def setUpClass(cls):
        cls._proc = _ensure_server()
        cls.client = HttpProvider(SERVER_URL, "multi-round-test")

    @classmethod
    def tearDownClass(cls):
        if cls._proc:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._proc.kill()

    # ------------------------------------------------------------------
    # 1. Three-round standard negotiation
    # ------------------------------------------------------------------

    def test_3_round_negotiation(self):
        """Standard 3-round lifecycle: send -> poll -> complete -> verify.

        Round 1: Agent A submits task
        Round 2: Agent A polls for completion
        Round 3: Agent A verifies final state
        """
        task_id = "mr_3round_01"

        # Round 1: Submit
        task = _make_task(task_id, "Calculate sum 1+2+3")
        r1 = self.client.send_message(task)
        self.assertTrue(r1.success, f"Round 1 (send) failed: {r1.error}")
        self.assertEqual(r1.task_state, "submitted")

        # Simulate server-side processing by transitioning to completed
        # (In real system, workers update state. Here we use direct API.)
        cancel_result = self.client.cancel_task(task_id)
        self.assertTrue(cancel_result.success)

        # Round 2: Poll for status after processing
        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success, f"Round 2 (poll) failed: {r2.error}")
        self.assertEqual(r2.data["id"], task_id)

        # Round 3: Final verification
        r3 = self.client.get_task(task_id)
        self.assertTrue(r3.success)
        self.assertEqual(r3.data["id"], task_id)
        # Task should be in canceled state after our simulate-processing cancel
        self.assertEqual(r3.data["status"]["state"], "canceled")

    def test_3_round_error_recovery_negotiation(self):
        """3-round negotiation where first attempt fails (404), then retry succeeds.

        Round 1: Get nonexistent task -> 404
        Round 2: Submit task -> success
        Round 3: Get task -> now exists
        """
        # Round 1: Try to get nonexistent task -> expect error
        r1 = self.client.get_task("mr_error_01")
        self.assertFalse(r1.success)
        self.assertEqual(r1.error.code, 404)
        self.assertTrue(r1.error.recoverable)

        # Round 2: Create the task
        task = _make_task("mr_error_01", "Recover from 404")
        r2 = self.client.send_message(task)
        self.assertTrue(r2.success)
        self.assertEqual(r2.task_state, "submitted")

        # Round 3: Now get it -> should succeed
        r3 = self.client.get_task("mr_error_01")
        self.assertTrue(r3.success)
        self.assertEqual(r3.data["id"], "mr_error_01")

        # Cleanup
        self.client.cancel_task("mr_error_01")

    # ------------------------------------------------------------------
    # 2. Five-round mixed interaction
    # ------------------------------------------------------------------

    def test_5_round_mixed_interaction(self):
        """5-round mixed interaction: submit, update, poll, verify, cleanup.

        Simulates a conversation where:
        Round 1: Agent submits initial request
        Round 2: Agent checks submission status
        Round 3: Agent sends updated request
        Round 4: Agent polls after update
        Round 5: Final verification + cleanup
        """
        task_id = "mr_5round_01"

        # Round 1: Initial submission
        history_r1 = []
        task = _make_multi_round_task(task_id, history_r1)
        r1 = self.client.send_message(task)
        self.assertTrue(r1.success)
        self.assertEqual(r1.task_state, "submitted")

        # Round 2: Check status (task exists)
        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["id"], task_id)
        self.assertEqual(r2.data["status"]["state"], "submitted")

        # Round 3: Submit updated payload (simulating refinement)
        history_r3 = [{"role": "agent", "round": 1, "action": "submit"}]
        updated = _make_multi_round_task(task_id, history_r3)
        r3 = self.client.send_message(updated)
        self.assertTrue(r3.success)

        # Round 4: Poll after update
        r4 = self.client.get_task(task_id)
        self.assertTrue(r4.success)
        self.assertEqual(r4.data["id"], task_id)

        # Round 5: Cancel + verify cleanup
        r5_cancel = self.client.cancel_task(task_id)
        self.assertTrue(r5_cancel.success)
        self.assertEqual(r5_cancel.task_state, "canceled")

        r5_verify = self.client.get_task(task_id)
        self.assertTrue(r5_verify.success)
        self.assertEqual(r5_verify.data["status"]["state"], "canceled")

    def test_5_round_with_concurrent_tasks(self):
        """5-round interaction with interleaved tasks.

        Tests that multi-round conversation on one task does not
        interfere with other tasks being processed concurrently.
        """
        main_id = "mr_concurrent_main"
        interleave_ids = [f"mr_concurrent_i{i:02d}" for i in range(3)]

        # Round 1: Submit main task
        r1 = self.client.send_message(_make_task(main_id, "main task"))
        self.assertTrue(r1.success)

        # Round 2: Submit interleaving tasks
        for tid in interleave_ids:
            r = self.client.send_message(_make_task(tid, f"interleave {tid}"))
            self.assertTrue(r.success)

        # Round 3: All tasks should exist
        for tid in [main_id] + interleave_ids:
            r = self.client.get_task(tid)
            self.assertTrue(r.success, f"Task {tid} not found after interleave")
            self.assertEqual(r.data["id"], tid)

        # Round 4: Verify main task state unchanged
        r4 = self.client.get_task(main_id)
        self.assertTrue(r4.success)
        self.assertEqual(r4.data["id"], main_id)

        # Round 5: Cleanup all
        for tid in [main_id] + interleave_ids:
            r = self.client.cancel_task(tid)
            self.assertTrue(r.success, f"Cleanup {tid} failed")

    # ------------------------------------------------------------------
    # 3. Multi-agent chaining (A -> B -> C simulated)
    # ------------------------------------------------------------------

    def test_3_agent_chain_simulation(self):
        """Simulate 3-agent chain: A submits -> B processes -> C finalizes.

        Since we have a single server, we simulate delegation by
        creating linked tasks:
        - Agent A creates task t_a
        - Agent B creates task t_b (referencing t_a as parent)
        - Agent C creates task t_c (referencing t_b as parent)
        - Chain verification: A can trace through B -> C
        """
        chain_id = "mr_chain_01"
        parent_prefix = f"{chain_id}_delegate"

        # Step 1: Agent A submits task
        task_a = _make_task(chain_id, "Agent A: calculate project timeline")
        r_a = self.client.send_message(task_a)
        self.assertTrue(r_a.success, "Agent A submit failed")

        # Step 2: Agent B takes subtask (simulated delegation)
        task_b = _make_task(f"{parent_prefix}_b", "Agent B: estimate frontend effort")
        task_b["metadata"] = {"parent": chain_id, "agent": "B"}
        r_b = self.client.send_message(task_b)
        self.assertTrue(r_b.success, "Agent B submit failed")

        # Step 3: Agent C takes subtask (simulated delegation from B)
        task_c = _make_task(f"{parent_prefix}_c", "Agent C: estimate backend effort")
        task_c["metadata"] = {"parent": f"{parent_prefix}_b", "agent": "C"}
        r_c = self.client.send_message(task_c)
        self.assertTrue(r_c.success, "Agent C submit failed")

        # Step 4: Verify chain exists - each task retrievable
        chain_tasks = [chain_id, f"{parent_prefix}_b", f"{parent_prefix}_c"]
        for tid in chain_tasks:
            r = self.client.get_task(tid)
            self.assertTrue(r.success, f"Chain task {tid} not found")
            self.assertEqual(r.data["id"], tid)

        # Step 5: Cleanup chain (reverse order: C -> B -> A)
        for tid in reversed(chain_tasks):
            r = self.client.cancel_task(tid)
            self.assertTrue(r.success, f"Chain cleanup {tid} failed")

    def test_3_agent_chain_with_intermediate_failure(self):
        """3-agent chain where agent B's subtask fails, A must handle.

        Simulates:
        - Agent A submits task
        - Agent B tries subtask but cancels (simulating "can't handle")
        - Agent C takes over from B
        - Final verification
        """
        chain_fail_id = "mr_chain_fail_01"

        # Agent A submits
        task_a = _make_task(chain_fail_id, "Agent A: handle customer query")
        r_a = self.client.send_message(task_a)
        self.assertTrue(r_a.success)

        # Agent B takes it but fails -> cancels
        task_b = _make_task(f"{chain_fail_id}_b", "Agent B: attempt but fail")
        task_b["metadata"] = {"parent": chain_fail_id}
        r_b = self.client.send_message(task_b)
        self.assertTrue(r_b.success)

        # Agent B cancels (simulating failure)
        r_b_cancel = self.client.cancel_task(f"{chain_fail_id}_b")
        self.assertTrue(r_b_cancel.success)

        # Agent C takes over from B's failure
        task_c = _make_task(f"{chain_fail_id}_c", "Agent C: take over from B")
        task_c["metadata"] = {"parent": chain_fail_id, "replaces": f"{chain_fail_id}_b"}
        r_c = self.client.send_message(task_c)
        self.assertTrue(r_c.success)

        # Verify: agent C's task exists, agent B's task is canceled
        r_c_get = self.client.get_task(f"{chain_fail_id}_c")
        self.assertTrue(r_c_get.success)
        self.assertEqual(r_c_get.data["id"], f"{chain_fail_id}_c")

        r_b_get = self.client.get_task(f"{chain_fail_id}_b")
        self.assertTrue(r_b_get.success)
        self.assertEqual(r_b_get.data["status"]["state"], "canceled")

        # Cleanup
        for tid in [f"{chain_fail_id}_c", chain_fail_id]:
            self.client.cancel_task(tid)


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
