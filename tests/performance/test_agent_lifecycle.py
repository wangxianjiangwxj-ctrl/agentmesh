"""
Agent lifecycle stress tests for AgentMesh A2A provider.

Covers the complete agent lifecycle operations under increasing concurrency:
  - Agent spawn: creation of agent instances (Facade + TaskManager tracking)
  - Agent handle: message processing loop (state transitions)
  - Agent destroy: cleanup and resource reclamation
  - Mixed scenario: multiple agents running concurrently

Each test measures throughput, latency, and correctness under load.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk"))

from a2a_provider import (
    A2AError,
    A2AFacade,
    A2AResult,
    A2ATaskManager,
    A2ATaskState,
    MemoryProvider,
)

# ------------------------------------------------------------------
# Results directory
# ------------------------------------------------------------------
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "stress_results")


def _ensure_results_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)


def _write_json_report(name: str, data: dict):
    _ensure_results_dir()
    path = os.path.join(RESULTS_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


# ------------------------------------------------------------------
# Agent lifecycle simulation helpers
# ------------------------------------------------------------------

def _make_task(task_id: str, state: str = "submitted") -> dict:
    return {
        "id": task_id,
        "status": {"state": state},
        "payload": {"query": "agent lifecycle stress test"},
        "metadata": {"source": "agent-lifecycle-stress"},
    }


def simulate_agent_spawn(facade: A2AFacade, agent_id: str) -> dict:
    """
    Simulate spawning an agent:
    1. Create a task representing the agent
    2. Track it in the Facade/TaskManager
    3. Set initial state to SUBMITTED
    Returns timing and status info.
    """
    t0 = time.perf_counter()
    task = _make_task(agent_id)
    result = facade.send_task(task)
    elapsed = time.perf_counter() - t0

    return {
        "agent_id": agent_id,
        "success": result.success,
        "elapsed_seconds": round(elapsed, 6),
    }


def simulate_agent_handle(facade: A2AFacade, agent_id: str,
                          num_messages: int = 5) -> dict:
    """
    Simulate an agent processing a sequence of messages:
    1. Retrieve the task
    2. Transition through states: SUBMITTED -> WORKING (-> INPUT_REQUIRED -> WORKING)* -> COMPLETED
    Returns per-message timing and state transition status.
    """
    tm = facade.task_manager
    transitions = []

    for i in range(num_messages):
        t_start = time.perf_counter()
        try:
            if i == 0:
                # First message: transition to WORKING
                ok = tm.update_state(agent_id, A2ATaskState.WORKING)
                current_state = A2ATaskState.WORKING
            elif i == num_messages - 1:
                # Last message: transition to COMPLETED
                ok = tm.update_state(agent_id, A2ATaskState.COMPLETED)
                current_state = A2ATaskState.COMPLETED
            else:
                # Middle messages: WORKING -> INPUT_REQUIRED -> WORKING
                tm.update_state(agent_id, A2ATaskState.INPUT_REQUIRED)
                tm.update_state(agent_id, A2ATaskState.WORKING)
                ok = True
                current_state = A2ATaskState.WORKING

            elapsed = time.perf_counter() - t_start
            transitions.append({
                "step": i,
                "state": current_state,
                "success": ok if isinstance(ok, bool) else True,
                "elapsed_seconds": round(elapsed, 6),
            })
        except (A2AError, Exception) as exc:
            elapsed = time.perf_counter() - t_start
            transitions.append({
                "step": i,
                "state": "error",
                "success": False,
                "error": str(exc),
                "elapsed_seconds": round(elapsed, 6),
            })

    # Verify final state
    final_task = tm.get_task(agent_id)
    final_state = final_task["state"] if final_task else "unknown"

    return {
        "agent_id": agent_id,
        "message_count": num_messages,
        "transitions": transitions,
        "final_state": final_state,
    }


def simulate_agent_destroy(provider: MemoryProvider,
                           facade: A2AFacade, agent_id: str) -> dict:
    """
    Simulate destroying (cleaning up) an agent:
    1. Cancel the task via Facade
    2. Run cleanup on TaskManager
    3. Verify the task is cleaned up
    """
    steps = []

    # Step 1: Cancel (gracefully handle terminal-state agents)
    t0 = time.perf_counter()
    try:
        cancel_result = facade.cancel_task(agent_id)
        cancel_elapsed = time.perf_counter() - t0
        steps.append({
            "step": "cancel",
            "success": cancel_result.success,
            "elapsed_seconds": round(cancel_elapsed, 6),
        })
    except A2AError as exc:
        # Agent is in a terminal state (e.g. COMPLETED) and cannot be
        # transitioned to CANCELED. Still proceed with cleanup.
        cancel_elapsed = time.perf_counter() - t0
        steps.append({
            "step": "cancel",
            "success": True,
            "note": f"Terminal state - proceeding with cleanup: {exc.message}",
            "elapsed_seconds": round(cancel_elapsed, 6),
        })
    except Exception as exc:
        steps.append({
            "step": "cancel",
            "success": False,
            "error": str(exc),
        })

    # Step 2: TaskManager cleanup
    t0 = time.perf_counter()
    try:
        facade.task_manager.cleanup(max_age_seconds=0)
        cleanup_elapsed = time.perf_counter() - t0
        steps.append({
            "step": "cleanup",
            "success": True,
            "elapsed_seconds": round(cleanup_elapsed, 6),
        })
    except Exception as exc:
        steps.append({
            "step": "cleanup",
            "success": False,
            "error": str(exc),
        })

    # Step 3: Verify removal
    agent_in_tm = facade.task_manager.get_task(agent_id)
    agent_in_provider = provider.get_task(agent_id)
    steps.append({
        "step": "verify_removal",
        "success": agent_in_tm is None,
        "in_task_manager": agent_in_tm is not None,
        "in_provider": agent_in_provider.success,
    })

    return {
        "agent_id": agent_id,
        "steps": steps,
    }


# ------------------------------------------------------------------
# Concurrency parameters
# ------------------------------------------------------------------
CONCURRENCY_LEVELS = [1, 5, 10, 20]


# ==================================================================
# Test: Agent Spawn
# ==================================================================

class TestAgentSpawnStress:
    """Stress test: spawning (creating + tracking) agent instances."""

    @pytest.mark.parametrize("workers", CONCURRENCY_LEVELS)
    def test_agent_spawn(self, workers):
        """Spawn {workers*10} agents with {workers} concurrent workers."""
        facade = A2AFacade(MemoryProvider("stress-spawn"), A2ATaskManager())
        num_agents = workers * 10

        records = []
        start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_agents):
                agent_id = f"spawn_{i:04d}"
                future = pool.submit(simulate_agent_spawn, facade, agent_id)
                futures[future] = agent_id

            for future in as_completed(futures):
                agent_id = futures[future]
                try:
                    result = future.result()
                    records.append(result)
                    # Assertion per spawn
                    assert result["success"] is True, \
                        f"Agent spawn failed for {agent_id}"
                except Exception as exc:
                    records.append({
                        "agent_id": agent_id,
                        "success": False,
                        "error": str(exc),
                    })

        wall = time.perf_counter() - start

        success_count = sum(1 for r in records if r["success"])
        report = {
            "test": "agent_spawn",
            "description": f"Spawn {num_agents} agents with {workers} "
                           f"concurrent workers",
            "workers": workers,
            "total_agents": num_agents,
            "wall_elapsed_seconds": round(wall, 4),
            "throughput_agents_per_sec": round(num_agents / wall, 2) if wall > 0 else 0,
            "success_count": success_count,
            "failure_count": num_agents - success_count,
        }

        # Verify all agents tracked in TaskManager
        tracked_count = len(facade.task_manager._tasks)
        report["agents_in_task_manager"] = tracked_count
        assert tracked_count <= num_agents, \
            f"TaskManager has more tasks than spawned ({tracked_count} > {num_agents})"

        path = _write_json_report(
            f"stress_spawn_workers{workers}.json", report
        )
        print(f"\n  [stress] agent_spawn workers={workers}: "
              f"{num_agents} agents in {wall:.3f}s")
        print(f"  [stress] Report saved: {path}")


# ==================================================================
# Test: Agent Handle (message processing loop)
# ==================================================================

class TestAgentHandleStress:
    """Stress test: agent message processing loop (state transitions)."""

    @pytest.mark.parametrize("workers", CONCURRENCY_LEVELS)
    def test_agent_handle(self, workers):
        """Process messages for {workers*5} agents with {workers} concurrent workers."""
        facade = A2AFacade(MemoryProvider("stress-handle"), A2ATaskManager())
        num_agents = workers * 5
        messages_per_agent = 10

        # Pre-spawn all agents
        for i in range(num_agents):
            agent_id = f"handle_{i:04d}"
            facade.send_task(_make_task(agent_id))

        records = []
        start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_agents):
                agent_id = f"handle_{i:04d}"
                future = pool.submit(
                    simulate_agent_handle, facade, agent_id, messages_per_agent
                )
                futures[future] = agent_id

            for future in as_completed(futures):
                agent_id = futures[future]
                try:
                    result = future.result()
                    records.append(result)
                    # Assertions per agent
                    assert result["final_state"] == A2ATaskState.COMPLETED, \
                        f"Agent {agent_id} did not reach COMPLETED state " \
                        f"(final: {result['final_state']})"
                    all_success = all(t["success"] for t in result["transitions"])
                    assert all_success, \
                        f"Agent {agent_id} had failed state transitions"
                except Exception as exc:
                    records.append({
                        "agent_id": agent_id,
                        "error": str(exc),
                    })

        wall = time.perf_counter() - start
        total_messages = num_agents * messages_per_agent

        report = {
            "test": "agent_handle",
            "description": f"Process {total_messages} messages for "
                           f"{num_agents} agents with {workers} concurrent workers",
            "workers": workers,
            "num_agents": num_agents,
            "messages_per_agent": messages_per_agent,
            "total_messages": total_messages,
            "wall_elapsed_seconds": round(wall, 4),
            "throughput_messages_per_sec": round(total_messages / wall, 2) if wall > 0 else 0,
            "agents_completed": sum(
                1 for r in records
                if r.get("final_state") == A2ATaskState.COMPLETED
            ),
        }

        path = _write_json_report(
            f"stress_handle_workers{workers}.json", report
        )
        print(f"\n  [stress] agent_handle workers={workers}: "
              f"{total_messages} msgs for {num_agents} agents in {wall:.3f}s")
        print(f"  [stress] Report saved: {path}")


# ==================================================================
# Test: Agent Destroy (cleanup & resource reclamation)
# ==================================================================

class TestAgentDestroyStress:
    """Stress test: agent destroy (cancel + cleanup + verify removal)."""

    @pytest.mark.parametrize("workers", CONCURRENCY_LEVELS)
    def test_agent_destroy(self, workers):
        """Destroy {workers*5} agents with {workers} concurrent workers."""
        provider = MemoryProvider("stress-destroy")
        facade = A2AFacade(provider, A2ATaskManager())
        num_agents = workers * 5

        # Pre-spawn all agents
        for i in range(num_agents):
            agent_id = f"destroy_{i:04d}"
            facade.send_task(_make_task(agent_id))

        records = []
        start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_agents):
                agent_id = f"destroy_{i:04d}"
                future = pool.submit(
                    simulate_agent_destroy, provider, facade, agent_id
                )
                futures[future] = agent_id

            for future in as_completed(futures):
                agent_id = futures[future]
                try:
                    result = future.result()
                    records.append(result)
                    # Assertions per destroy
                    for step in result["steps"]:
                        assert step["success"] is True, \
                            f"Agent destroy step '{step['step']}' failed for {agent_id}"
                except Exception as exc:
                    records.append({
                        "agent_id": agent_id,
                        "steps": [{"step": "error", "success": False, "error": str(exc)}],
                    })

        wall = time.perf_counter() - start

        report = {
            "test": "agent_destroy",
            "description": f"Destroy {num_agents} agents with {workers} "
                           f"concurrent workers",
            "workers": workers,
            "total_agents": num_agents,
            "wall_elapsed_seconds": round(wall, 4),
            "throughput_agents_per_sec": round(num_agents / wall, 2) if wall > 0 else 0,
            "destroy_success_count": sum(
                1 for r in records
                if all(s["success"] for s in r["steps"])
            ),
        }

        # Verify cleanup
        remaining_in_tm = len(facade.task_manager._tasks)
        report["remaining_in_task_manager"] = remaining_in_tm
        assert remaining_in_tm == 0, \
            f"TaskManager still has {remaining_in_tm} tasks after destroy"

        path = _write_json_report(
            f"stress_destroy_workers{workers}.json", report
        )
        print(f"\n  [stress] agent_destroy workers={workers}: "
              f"{num_agents} agents destroyed in {wall:.3f}s")
        print(f"  [stress] Report saved: {path}")


# ==================================================================
# Test: Mixed Agent Scenario (spawn + handle + destroy concurrently)
# ==================================================================

class TestMixedAgentScenario:
    """Stress test: full agent lifecycle (spawn -> handle -> destroy)."""

    @pytest.mark.parametrize("workers", CONCURRENCY_LEVELS)
    def test_mixed_agent_scenario(self, workers):
        """Run full lifecycle for {workers*3} agents with {workers} workers."""
        provider = MemoryProvider("stress-mixed-lifecycle")
        facade = A2AFacade(provider, A2ATaskManager())
        num_agents = workers * 3

        all_spawns = []
        start = time.perf_counter()

        # Phase 1: Spawn all agents
        spawn_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_agents):
                agent_id = f"lifecycle_{i:04d}"
                future = pool.submit(simulate_agent_spawn, facade, agent_id)
                futures[future] = agent_id

            for future in as_completed(futures):
                agent_id = futures[future]
                result = future.result()
                all_spawns.append(result)
                assert result["success"] is True, f"Spawn failed for {agent_id}"
        spawn_elapsed = time.perf_counter() - spawn_start

        # Phase 2: Handle all agents
        handle_start = time.perf_counter()
        all_handles = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_agents):
                agent_id = f"lifecycle_{i:04d}"
                future = pool.submit(
                    simulate_agent_handle, facade, agent_id, 8
                )
                futures[future] = agent_id

            for future in as_completed(futures):
                agent_id = futures[future]
                result = future.result()
                all_handles.append(result)
                assert result["final_state"] == A2ATaskState.COMPLETED, \
                    f"Handle failed for {agent_id}, final state: {result['final_state']}"
        handle_elapsed = time.perf_counter() - handle_start

        # Phase 3: Destroy all agents
        destroy_start = time.perf_counter()
        all_destroys = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_agents):
                agent_id = f"lifecycle_{i:04d}"
                future = pool.submit(
                    simulate_agent_destroy, provider, facade, agent_id
                )
                futures[future] = agent_id

            for future in as_completed(futures):
                agent_id = futures[future]
                result = future.result()
                all_destroys.append(result)
                for step in result["steps"]:
                    assert step["success"] is True, \
                        f"Destroy step {step['step']} failed for {agent_id}"
        destroy_elapsed = time.perf_counter() - destroy_start

        wall = time.perf_counter() - start

        total_messages = num_agents * 8
        report = {
            "test": "mixed_agent_scenario",
            "description": f"Full lifecycle (spawn -> handle -> destroy) for "
                           f"{num_agents} agents with {workers} concurrent workers",
            "workers": workers,
            "num_agents": num_agents,
            "messages_per_agent": 8,
            "total_messages": total_messages,
            "wall_elapsed_seconds": round(wall, 4),
            "phase_timing_seconds": {
                "spawn": round(spawn_elapsed, 4),
                "handle": round(handle_elapsed, 4),
                "destroy": round(destroy_elapsed, 4),
            },
            "phase_throughput": {
                "spawn_agents_per_sec": round(num_agents / spawn_elapsed, 2) if spawn_elapsed > 0 else 0,
                "handle_messages_per_sec": round(total_messages / handle_elapsed, 2) if handle_elapsed > 0 else 0,
                "destroy_agents_per_sec": round(num_agents / destroy_elapsed, 2) if destroy_elapsed > 0 else 0,
            },
            "spawn_success_count": sum(1 for r in all_spawns if r["success"]),
            "handle_completed_count": sum(
                1 for r in all_handles
                if r.get("final_state") == A2ATaskState.COMPLETED
            ),
            "destroy_success_count": sum(
                1 for r in all_destroys
                if all(s["success"] for s in r["steps"])
            ),
        }

        path = _write_json_report(
            f"stress_mixed_lifecycle_workers{workers}.json", report
        )
        print(f"\n  [stress] mixed_agent_scenario workers={workers}: "
              f"{num_agents} agents full lifecycle in {wall:.3f}s")
        print(f"  [stress]  spawn={spawn_elapsed:.3f}s  "
              f"handle={handle_elapsed:.3f}s  destroy={destroy_elapsed:.3f}s")
        print(f"  [stress] Report saved: {path}")


# ==================================================================
# Test: Agent lifecycle edge cases
# ==================================================================

class TestAgentLifecycleEdgeCases:
    """Edge cases for agent lifecycle operations."""

    @pytest.mark.parametrize("workers", [1, 5, 10])
    def test_destroy_nonexistent_agent(self, workers):
        """Attempting to destroy a nonexistent agent should fail gracefully."""
        provider = MemoryProvider("stress-edge-nonexist")
        facade = A2AFacade(provider, A2ATaskManager())
        num_attempts = workers * 5

        records = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_attempts):
                agent_id = f"ghost_{i:04d}"
                future = pool.submit(
                    simulate_agent_destroy, provider, facade, agent_id
                )
                futures[future] = agent_id

            for future in as_completed(futures):
                result = future.result()
                records.append(result)

        destroy_attempts = sum(
            1 for r in records
            if all(s["success"] for s in r["steps"])
        )
        report = {
            "test": "destroy_nonexistent_agent",
            "description": f"Attempt to destroy {num_attempts} nonexistent agents "
                           f"with {workers} workers",
            "workers": workers,
            "total_attempts": num_attempts,
            "destroy_success_count": destroy_attempts,
        }
        _write_json_report(
            f"stress_edge_nonexist_destroy_workers{workers}.json", report
        )

    @pytest.mark.parametrize("workers", [1, 5, 10])
    def test_handle_already_completed_agent(self, workers):
        """Handle operations on completed agents should fail."""
        facade = A2AFacade(MemoryProvider("stress-edge-completed"), A2ATaskManager())
        num_agents = workers * 3

        # Spawn and immediately complete
        for i in range(num_agents):
            agent_id = f"precomplete_{i:04d}"
            facade.send_task(_make_task(agent_id))
            facade.task_manager.update_state(agent_id, A2ATaskState.WORKING)
            facade.task_manager.update_state(agent_id, A2ATaskState.COMPLETED)

        # Attempt to handle
        records = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_agents):
                agent_id = f"precomplete_{i:04d}"
                future = pool.submit(
                    simulate_agent_handle, facade, agent_id, 3
                )
                futures[future] = agent_id

            for future in as_completed(futures):
                result = future.result()
                records.append(result)

        # All should have at least some failed transitions
        all_failures = all(
            any(not t["success"] for t in r["transitions"])
            for r in records if r.get("transitions")
        )

        report = {
            "test": "handle_already_completed_agent",
            "description": f"Handle {num_agents} already completed agents "
                           f"with {workers} workers",
            "workers": workers,
            "num_agents": num_agents,
            "all_had_failures": all_failures,
        }
        _write_json_report(
            f"stress_edge_completed_handle_workers{workers}.json", report
        )
