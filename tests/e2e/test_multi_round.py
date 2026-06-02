#!/usr/bin/env python3
"""Multi-round conversation tests for A2A HTTP Server.

Tests complex multi-turn agent interactions:
  1. 3-round standard negotiation (send_task → get_task → cancel)
  2. 5-round mixed interaction with progressive payloads
  3. Multi-agent chaining (A→B→C task forwarding)

Usage:
    pytest tests/e2e/test_multi_round.py -v
"""

from __future__ import annotations

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
    from agentmesh.a2a_server import HttpProvider
    from agentmesh.a2a_provider import A2AError
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from agentmesh.a2a_server import HttpProvider
    from agentmesh.a2a_provider import A2AError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_PORT = int(os.environ.get("A2A_SERVER_PORT", "8089"))
SERVER_URL = f"http://localhost:{SERVER_PORT}"
SERVER_START_WAIT = 3

# how many rounds in each scenario
ROUNDS_STANDARD = 3
ROUNDS_MIXED = 5


# ---------------------------------------------------------------------------
# Server lifecycle fixture
# ---------------------------------------------------------------------------

class MultiRoundTest(unittest.TestCase):
    """Multi-round A2A conversation tests."""

    @classmethod
    def setUpClass(cls):
        """Start server if not already running."""
        # Check if server responds
        cls.server_proc = None
        try:
            import urllib.request
            req = urllib.request.Request(f"{SERVER_URL}/ping", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                cls.server_running = True
        except Exception:
            cls.server_running = False
            cls.server_proc = subprocess.Popen(
                [sys.executable, "-m", "agentmesh.a2a_server", "server",
                 "--port", str(SERVER_PORT)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(SERVER_START_WAIT)

        cls.client = HttpProvider(SERVER_URL)

    @classmethod
    def tearDownClass(cls):
        """Shutdown server if we started it."""
        if cls.server_proc:
            cls.server_proc.terminate()
            try:
                cls.server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server_proc.kill()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _assert_success(self, result, msg_prefix: str):
        self.assertTrue(
            result.success,
            f"{msg_prefix}: expected success, got error={result.error}",
        )

    def _assert_state(self, result, expected_state: str, msg_prefix: str):
        self.assertEqual(
            result.task_state,
            expected_state,
            f"{msg_prefix}: expected state '{expected_state}', got '{result.task_state}'",
        )

    def _make_task(self, task_id: str, text: str, round_num: int = 0) -> dict:
        return {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {"text": text, "round": round_num},
            "metadata": {"source": "multi_round_test", "round": round_num},
        }

    def _make_task_with_artifacts(self, task_id: str, text: str,
                                  artifacts: dict, round_num: int = 0) -> dict:
        task = self._make_task(task_id, text, round_num)
        task["artifacts"] = artifacts
        return task

    # ------------------------------------------------------------------
    # Test: 3-round standard negotiation
    # ------------------------------------------------------------------

    def test_3round_standard_negotiation(self):
        """Scenario 1: 3-round standard A2A task negotiation.

        Round 1: send_task  → submitted
        Round 2: get_task   → verify state
        Round 3: cancel     → canceled
        """
        task_id = "round3_001"
        task = self._make_task(task_id, "Round 1: initial task")

        # Round 1: Send
        r = self.client.send_message(task)
        self._assert_success(r, "R1 send")
        self._assert_state(r, "submitted", "R1 send")

        # Round 2: Get
        r = self.client.get_task(task_id)
        self._assert_success(r, "R2 get")
        self.assertEqual(r.data["id"], task_id, "R2: task id mismatch")
        self.assertEqual(r.data["payload"]["text"], "Round 1: initial task",
                         "R2: payload text mismatch")

        # Round 3: Cancel
        r = self.client.cancel_task(task_id)
        self._assert_success(r, "R3 cancel")
        self._assert_state(r, "canceled", "R3 cancel")

    def test_3round_sequential_tasks(self):
        """3 rounds with 3 different tasks in sequence: send→cancel sequence."""
        for i in range(1, ROUNDS_STANDARD + 1):
            tid = f"seq_r{i:03d}"
            task = self._make_task(tid, f"Sequential task #{i}", round_num=i)

            r = self.client.send_message(task)
            self._assert_success(r, f"Seq round {i} send")

            r = self.client.get_task(tid)
            self._assert_success(r, f"Seq round {i} get")
            self.assertEqual(r.data["payload"]["text"], f"Sequential task #{i}",
                             f"Seq round {i}: text mismatch")

            r = self.client.cancel_task(tid)
            self._assert_success(r, f"Seq round {i} cancel")

    # ------------------------------------------------------------------
    # Test: 5-round mixed interaction with progressive payloads
    # ------------------------------------------------------------------

    def test_5round_mixed_interaction(self):
        """Scenario 2: 5-round mixed interaction.

        Each round adds progressive payload complexity:
        R1: plain text
        R2: text + metadata
        R3: text + nested payload
        R4: text + artifacts
        R5: full lifecycle with all fields
        """
        client = self.client
        base_id = "mixed_5r"

        # R1: plain text
        t1 = self._make_task(f"{base_id}_r1", "Plain text message", round_num=1)
        r = client.send_message(t1)
        self._assert_success(r, "R1 plain text")

        r = client.get_task(f"{base_id}_r1")
        self._assert_success(r, "R1 get")
        self.assertEqual(r.data["payload"]["text"], "Plain text message")

        # R2: text + metadata enrichment
        t2 = self._make_task(f"{base_id}_r2", "With metadata", round_num=2)
        t2["metadata"]["priority"] = "high"
        t2["metadata"]["context"] = {"session": "test", "user": "alice"}
        r = client.send_message(t2)
        self._assert_success(r, "R2 with metadata")

        r = client.get_task(f"{base_id}_r2")
        self._assert_success(r, "R2 get")
        self.assertEqual(r.data["metadata"]["priority"], "high")
        self.assertEqual(r.data["metadata"]["context"]["user"], "alice")

        # R3: text + nested payload
        t3 = self._make_task(f"{base_id}_r3", "Nested payload", round_num=3)
        t3["payload"]["nested"] = {
            "query": "weather",
            "params": {"city": "Shanghai", "unit": "celsius"},
            "options": ["detailed", "summary"],
        }
        r = client.send_message(t3)
        self._assert_success(r, "R3 nested payload")

        r = client.get_task(f"{base_id}_r3")
        self._assert_success(r, "R3 get")
        self.assertEqual(
            r.data["payload"]["nested"]["params"]["city"], "Shanghai"
        )

        # R4: text + artifacts
        t4 = self._make_task_with_artifacts(
            f"{base_id}_r4", "With artifacts",
            {"result": "42", "confidence": 0.95, "sources": ["src1", "src2"]},
            round_num=4,
        )
        r = client.send_message(t4)
        self._assert_success(r, "R4 with artifacts")

        r = client.get_task(f"{base_id}_r4")
        self._assert_success(r, "R4 get")
        self.assertEqual(r.data["artifacts"]["result"], "42")
        self.assertEqual(len(r.data["artifacts"]["sources"]), 2)

        # R5: full lifecycle — send, verify, cancel
        t5 = self._make_task_with_artifacts(
            f"{base_id}_r5", "Full round trip",
            {"summary": "all tests pass"},
            round_num=5,
        )
        r = client.send_message(t5)
        self._assert_success(r, "R5 send")
        self._assert_state(r, "submitted", "R5 send")

        r = client.get_task(f"{base_id}_r5")
        self._assert_success(r, "R5 get")
        self.assertEqual(r.data["payload"]["round"], 5)

        r = client.cancel_task(f"{base_id}_r5")
        self._assert_success(r, "R5 cancel")
        self._assert_state(r, "canceled", "R5 cancel")

        # Verify previous tasks are unaffected
        r = client.get_task(f"{base_id}_r1")
        self._assert_success(r, "R1 still accessible after R5")

        r = client.get_task(f"{base_id}_r3")
        self._assert_success(r, "R3 still accessible after R5")

    # ------------------------------------------------------------------
    # Test: Multi-agent chaining (A→B→C)
    # ------------------------------------------------------------------

    def test_multi_agent_chain(self):
        """Scenario 3: Multi-agent chaining A→B→C.

        Simulates:
        1. Agent A sends a task
        2. Agent B retrieves and processes it (simulated by payload update)
        3. Agent C retrieves the final state

        In a real deployment, each agent would be a separate service.
        Here we verify the store supports the access pattern.
        """
        client = self.client

        # A sends task
        task_a = self._make_task("chain_abc_001", "Agent A: initial query", round_num=1)
        r = client.send_message(task_a)
        self._assert_success(r, "A sends task")

        # B reads task (simulates B taking ownership)
        r = client.get_task("chain_abc_001")
        self._assert_success(r, "B reads task from A")
        self.assertEqual(r.data["payload"]["text"], "Agent A: initial query")

        # B sends progress update via a new task referencing parent
        task_b = self._make_task("chain_abc_002", "Agent B: processing step", round_num=2)
        task_b["metadata"]["parent_task"] = "chain_abc_001"
        task_b["metadata"]["agent"] = "agent_b"
        r = client.send_message(task_b)
        self._assert_success(r, "B sends follow-up task")

        # C reads both tasks (simulates C consuming results)
        r_a = client.get_task("chain_abc_001")
        r_b = client.get_task("chain_abc_002")
        self._assert_success(r_a, "C reads A's task")
        self._assert_success(r_b, "C reads B's task")

        # Verify chain metadata
        self.assertEqual(r_b.data["metadata"]["parent_task"], "chain_abc_001")
        self.assertEqual(r_b.data["metadata"]["agent"], "agent_b")

        # Clean up all tasks in chain
        for tid in ["chain_abc_001", "chain_abc_002"]:
            r = client.cancel_task(tid)
            self._assert_success(r, f"Cleanup {tid}")

    def test_multi_agent_chain_3link(self):
        """3-link agent chain: A→B→C→D.

        4 tasks with linear dependency chain:
        A creates → B references → C references → D references
        """
        client = self.client
        agents = ["agent_a", "agent_b", "agent_c", "agent_d"]
        task_ids = [f"chain_3link_{i:03d}" for i in range(4)]

        # Build chain forward
        for i, (agent, tid) in enumerate(zip(agents, task_ids)):
            text = f"{agent}: step {i + 1} of chain"
            task = self._make_task(tid, text, round_num=i + 1)
            task["metadata"]["agent"] = agent
            if i > 0:
                task["metadata"]["prev_task"] = task_ids[i - 1]
            r = client.send_message(task)
            self._assert_success(r, f"{agent} sends task")

        # Verify chain backward
        for i in range(len(task_ids) - 1, -1, -1):
            r = client.get_task(task_ids[i])
            self._assert_success(r, f"Verify task {task_ids[i]}")
            self.assertEqual(r.data["metadata"]["agent"], agents[i])
            if i > 0:
                self.assertEqual(r.data["metadata"]["prev_task"], task_ids[i - 1])

        # Cleanup
        for tid in task_ids:
            r = client.cancel_task(tid)
            self._assert_success(r, f"Cleanup {tid}")

    # ------------------------------------------------------------------
    # Test: Concurrent multi-round sessions
    # ------------------------------------------------------------------

    def test_concurrent_multi_round_sessions(self):
        """Multiple independent multi-round sessions running concurrently.

        Session A: 3 rounds (send→get→cancel)
        Session B: 3 rounds (send→get→cancel)

        Both interleaved to verify session isolation.
        """
        client = self.client

        # Session A tasks
        a_tasks = [
            self._make_task(f"concur_a_{i:03d}", f"Session A round {i}", round_num=i)
            for i in range(1, ROUNDS_STANDARD + 1)
        ]

        # Session B tasks
        b_tasks = [
            self._make_task(f"concur_b_{i:03d}", f"Session B round {i}", round_num=i)
            for i in range(1, ROUNDS_STANDARD + 1)
        ]

        # Interleaved send
        for a_t, b_t in zip(a_tasks, b_tasks):
            r_a = client.send_message(a_t)
            self._assert_success(r_a, f"Concurrent A send {a_t['id']}")
            r_b = client.send_message(b_t)
            self._assert_success(r_b, f"Concurrent B send {b_t['id']}")

        # Interleaved get — verify isolation
        for a_t, b_t in zip(a_tasks, b_tasks):
            r_a = client.get_task(a_t["id"])
            self._assert_success(r_a, f"Concurrent A get {a_t['id']}")
            self.assertEqual(
                r_a.data["payload"]["text"], f"Session A round {a_t['payload']['round']}"
            )

            r_b = client.get_task(b_t["id"])
            self._assert_success(r_b, f"Concurrent B get {b_t['id']}")
            self.assertEqual(
                r_b.data["payload"]["text"], f"Session B round {b_t['payload']['round']}"
            )

        # Interleaved cancel
        for a_t, b_t in zip(a_tasks, b_tasks):
            r_a = client.cancel_task(a_t["id"])
            self._assert_success(r_a, f"Concurrent A cancel {a_t['id']}")
            r_b = client.cancel_task(b_t["id"])
            self._assert_success(r_b, f"Concurrent B cancel {b_t['id']}")

        # Verify all canceled
        for a_t, b_t in zip(a_tasks, b_tasks):
            r_a = client.get_task(a_t["id"])
            r_b = client.get_task(b_t["id"])
            # After cancel, task should exist (get succeeds) but not be in submitted
            self._assert_success(r_a, f"Verify A {a_t['id']} after cancel")
            self._assert_success(r_b, f"Verify B {b_t['id']} after cancel")


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
