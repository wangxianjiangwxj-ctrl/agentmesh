# AgentMesh A2A — End-to-End Integration Test Skeleton
#
# Phase 13, Direction 5: Real Agent Framework Integration.
# This module defines the integration test matrix and verification scenarios
# for cross-framework agent communication through AgentMesh.
#
# The test matrix covers 8 scenarios:
#   CrewAI  --> CrewAI     (TextCard)
#   CrewAI  --> AutoGen    (TextCard)
#   AutoGen --> AutoGen    (TextCard)
#   AutoGen --> CrewAI     (TextCard)
#   Custom  --> CrewAI     (DataCard)
#   Custom  --> AutoGen    (DataCard)
#   CrewAI  --> Custom     (ToolCallCard)
#   AutoGen --> Custom     (ToolCallCard)
#
# Usage (standalone):
#   python -m agentmesh.a2a.integration.e2e_test
#
# Usage (pytest):
#   See tests/integration/test_e2e.py
#
# Reference: research/phase13-integration-plan.md — Task 4

from __future__ import annotations

import abc
import dataclasses
import enum
import json
import sys
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

T = TypeVar("T")

AgentFactory = Callable[[], Any]
MessagePayload = Dict[str, Any]


# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------

class FrameworkType(str, enum.Enum):
    """Agent framework types in the integration test matrix."""

    CREWAI = "crewai"
    AUTOGEN = "autogen"
    CUSTOM = "custom"


class TestResult(str, enum.Enum):
    """Result of a single test scenario."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class TestScenario:
    """Definition of a single integration test scenario.

    Attributes:
        name: Human-readable scenario name.
        sender_framework: Framework type of the sending agent.
        receiver_framework: Framework type of the receiving agent.
        message_type: Type of message/card to send.
        description: Detailed scenario description.
        prerequisites: List of framework packages required (e.g. ["crewai"]).
    """

    name: str
    sender_framework: FrameworkType
    receiver_framework: FrameworkType
    message_type: str
    description: str
    prerequisites: List[str]


@dataclasses.dataclass(frozen=True)
class ScenarioResult:
    """Result of executing a test scenario.

    Attributes:
        scenario: The scenario definition.
        result: Pass/fail/skip/blocked.
        duration_seconds: Time taken to execute.
        error_message: Error details if failed.
        traceback_str: Full traceback if failed (for diagnostics).
    """

    scenario: TestScenario
    result: TestResult
    duration_seconds: float
    error_message: Optional[str] = None
    traceback_str: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class IntegrationTestMatrix:
    """The full integration test matrix with metadata.

    Attributes:
        scenarios: All scenarios defined for this matrix.
        framework_versions: Version info for each framework used.
        environment_info: Additional environment metadata.
    """

    scenarios: List[TestScenario]
    framework_versions: Dict[str, str]
    environment_info: Dict[str, str]


# ---------------------------------------------------------------------------
# Default test matrix
# ---------------------------------------------------------------------------

DEFAULT_MATRIX = IntegrationTestMatrix(
    scenarios=[
        TestScenario(
            name="crewai_to_crewai_text",
            sender_framework=FrameworkType.CREWAI,
            receiver_framework=FrameworkType.CREWAI,
            message_type="text",
            description="CrewAI agent sends a TextCard to another CrewAI agent",
            prerequisites=["crewai"],
        ),
        TestScenario(
            name="crewai_to_autogen_text",
            sender_framework=FrameworkType.CREWAI,
            receiver_framework=FrameworkType.AUTOGEN,
            message_type="text",
            description="CrewAI agent sends a TextCard to an AutoGen agent",
            prerequisites=["crewai", "pyautogen"],
        ),
        TestScenario(
            name="autogen_to_autogen_text",
            sender_framework=FrameworkType.AUTOGEN,
            receiver_framework=FrameworkType.AUTOGEN,
            message_type="text",
            description="AutoGen agent sends a message to another AutoGen agent",
            prerequisites=["pyautogen"],
        ),
        TestScenario(
            name="autogen_to_crewai_text",
            sender_framework=FrameworkType.AUTOGEN,
            receiver_framework=FrameworkType.CREWAI,
            message_type="text",
            description="AutoGen agent sends a message to a CrewAI agent",
            prerequisites=["crewai", "pyautogen"],
        ),
        TestScenario(
            name="custom_to_crewai_data",
            sender_framework=FrameworkType.CUSTOM,
            receiver_framework=FrameworkType.CREWAI,
            message_type="data",
            description="Custom agent sends a DataCard to a CrewAI agent",
            prerequisites=["crewai"],
        ),
        TestScenario(
            name="custom_to_autogen_data",
            sender_framework=FrameworkType.CUSTOM,
            receiver_framework=FrameworkType.AUTOGEN,
            message_type="data",
            description="Custom agent sends a DataCard to an AutoGen agent",
            prerequisites=["pyautogen"],
        ),
        TestScenario(
            name="crewai_to_custom_tool_call",
            sender_framework=FrameworkType.CREWAI,
            receiver_framework=FrameworkType.CUSTOM,
            message_type="tool_call",
            description="CrewAI agent sends a ToolCallCard to a custom agent",
            prerequisites=["crewai"],
        ),
        TestScenario(
            name="autogen_to_custom_tool_call",
            sender_framework=FrameworkType.AUTOGEN,
            receiver_framework=FrameworkType.CUSTOM,
            message_type="tool_call",
            description="AutoGen agent sends a ToolCallCard to a custom agent",
            prerequisites=["pyautogen"],
        ),
    ],
    framework_versions={},
    environment_info={
        "python_version": sys.version,
    },
)


# ---------------------------------------------------------------------------
# Abstract test runner
# ---------------------------------------------------------------------------

class IntegrationTestRunner(abc.ABC):
    """Abstract base for integration test execution.

    Subclasses implement the actual agent creation and message exchange
    logic for each scenario in the test matrix.
    """

    def __init__(self, matrix: Optional[IntegrationTestMatrix] = None) -> None:
        """Initialize the test runner with a test matrix.

        Args:
            matrix: Integration test matrix; defaults to DEFAULT_MATRIX.
        """
        self._matrix = matrix or DEFAULT_MATRIX
        self._results: List[ScenarioResult] = []

    @property
    def matrix(self) -> IntegrationTestMatrix:
        """Get the test matrix."""
        return self._matrix

    @property
    def results(self) -> List[ScenarioResult]:
        """Get accumulated test results from the last run."""
        return list(self._results)

    # ------------------------------------------------------------------
    # Scenario execution
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def setup_scenario(self, scenario: TestScenario) -> Dict[str, Any]:
        """Prepare the environment for a specific test scenario.

        Creates and registers the sender and receiver agents according
        to the scenario definition. Returns a context dict with agent
        references needed by execute_scenario().

        Args:
            scenario: The scenario to set up.

        Returns:
            Context dict with at least "sender_id" and "receiver_id" keys.
            May include additional framework-specific agent references.

        Raises:
            ImportError: If a required framework is not installed.
        """
        ...

    @abc.abstractmethod
    def execute_scenario(
        self,
        scenario: TestScenario,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a single test scenario.

        Sends a message/card from the sender to the receiver and waits
        for delivery confirmation.

        Args:
            scenario: The scenario to execute.
            context: Context dict from setup_scenario().

        Returns:
            Dict with:
              - "sent": dict with sender_id, receiver_id, payload, message_type
              - "received": dict with card/message content and metadata
              - "latency_ms": round-trip latency in milliseconds

        Raises:
            RuntimeError: If message exchange fails.
        """
        ...

    @abc.abstractmethod
    def teardown_scenario(self, scenario: TestScenario, context: Dict[str, Any]) -> None:
        """Clean up resources after a scenario.

        Unregisters agents and releases any framework-specific resources.

        Args:
            scenario: The scenario that was executed.
            context: Context dict from setup_scenario().
        """
        ...

    @abc.abstractmethod
    def validate_result(
        self,
        scenario: TestScenario,
        result_data: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Validate that a scenario produced the expected result.

        Checks message content integrity, delivery confirmation, and
        framework-specific expectations.

        Args:
            scenario: The scenario that was executed.
            result_data: Dict returned by execute_scenario().

        Returns:
            Tuple of (passed: bool, error_message: Optional[str]).
        """
        ...

    # ------------------------------------------------------------------
    # Full run orchestration
    # ------------------------------------------------------------------

    def run_all(self) -> List[ScenarioResult]:
        """Execute all scenarios in the test matrix.

        Iterates through all scenarios, running setup -> execute ->
        validate -> teardown for each. Scenarios whose prerequisites
        are not met are marked as SKIPPED.

        Returns:
            List of ScenarioResult for each scenario.
        """
        self._results = []
        for scenario in self.matrix.scenarios:
            result = self._run_single(scenario)
            self._results.append(result)
        return self._results

    def run_scenario(self, scenario_name: str) -> Optional[ScenarioResult]:
        """Execute a single scenario by name.

        Args:
            scenario_name: Name of the scenario (from TestScenario.name).

        Returns:
            ScenarioResult, or None if no scenario matches.
        """
        for scenario in self.matrix.scenarios:
            if scenario.name == scenario_name:
                result = self._run_single(scenario)
                self._results.append(result)
                return result
        return None

    def _run_single(self, scenario: TestScenario) -> ScenarioResult:
        """Internal: run a single scenario with timing and error handling."""
        missing = [pkg for pkg in scenario.prerequisites if not self._check_prerequisite(pkg)]
        if missing:
            return ScenarioResult(
                scenario=scenario,
                result=TestResult.SKIPPED,
                duration_seconds=0.0,
                error_message=f"Missing prerequisites: {', '.join(missing)}",
            )

        start = time.monotonic()
        context: Optional[Dict[str, Any]] = None
        try:
            context = self.setup_scenario(scenario)
            result_data = self.execute_scenario(scenario, context)
            passed, err = self.validate_result(scenario, result_data)
            duration = time.monotonic() - start
            return ScenarioResult(
                scenario=scenario,
                result=TestResult.PASSED if passed else TestResult.FAILED,
                duration_seconds=duration,
                error_message=err,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            return ScenarioResult(
                scenario=scenario,
                result=TestResult.FAILED,
                duration_seconds=duration,
                error_message=str(exc),
                traceback_str=traceback.format_exc(),
            )
        finally:
            if context is not None:
                try:
                    self.teardown_scenario(scenario, context)
                except Exception:
                    pass  # Best-effort cleanup

    # ------------------------------------------------------------------
    # Prerequisite checks
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _check_prerequisite(self, package_name: str) -> bool:
        """Check if a required package is installed.

        Args:
            package_name: Python package name (e.g. "crewai", "pyautogen").

        Returns:
            True if importable, False otherwise.
        """
        ...

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summary_report(self) -> Dict[str, Any]:
        """Generate a summary report of the latest test run.

        Returns:
            Dict with:
              - "total": int
              - "passed": int
              - "failed": int
              - "skipped": int
              - "blocked": int
              - "duration_seconds": float (total)
              - "details": List[Dict] per scenario
        """
        if not self._results:
            return {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "blocked": 0, "duration_seconds": 0.0, "details": []}

        total = len(self._results)
        passed = sum(1 for r in self._results if r.result == TestResult.PASSED)
        failed = sum(1 for r in self._results if r.result == TestResult.FAILED)
        skipped = sum(1 for r in self._results if r.result == TestResult.SKIPPED)
        blocked = sum(1 for r in self._results if r.result == TestResult.BLOCKED)
        total_duration = sum(r.duration_seconds for r in self._results)

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "blocked": blocked,
            "duration_seconds": round(total_duration, 3),
            "details": [
                {
                    "name": r.scenario.name,
                    "result": r.result.value,
                    "duration": round(r.duration_seconds, 3),
                    "error": r.error_message,
                }
                for r in self._results
            ],
        }


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def run_verification_matrix(
    runner_class: Optional[type] = None,
    matrix: Optional[IntegrationTestMatrix] = None,
) -> int:
    """Run the integration test matrix and print a summary.

    This is the primary entry point for running the verification matrix
    outside of pytest (e.g., in CI or as a standalone script).

    Args:
        runner_class: A concrete IntegrationTestRunner subclass. If None,
                      prints a message that no runner is registered.
        matrix: Optional custom test matrix. Defaults to DEFAULT_MATRIX.

    Returns:
        Exit code: 0 if all tests pass, 1 otherwise.
    """
    if runner_class is None:
        print("=" * 60)
        print("AgentMesh Integration Test Matrix (Skeleton)")
        print("=" * 60)
        print()
        print("No concrete test runner registered.")
        print("Subclass IntegrationTestRunner and implement the abstract methods.")
        print()
        print("Scenarios defined:", len(DEFAULT_MATRIX.scenarios))
        for s in DEFAULT_MATRIX.scenarios:
            status = "SKIP (needs: " + ", ".join(s.prerequisites) + ")"
            print(f"  [{status:40s}] {s.name}")
        print()
        print("Run via pytest: pytest tests/integration/test_e2e.py -v")
        return 0

    runner = runner_class(matrix=matrix)
    print(f"Running {len(runner.matrix.scenarios)} integration scenarios...")
    results = runner.run_all()
    report = runner.summary_report()

    print()
    print("=" * 60)
    print("Integration Test Report")
    print("=" * 60)
    print(f"  Total:   {report['total']}")
    print(f"  Passed:  {report['passed']}")
    print(f"  Failed:  {report['failed']}")
    print(f"  Skipped: {report['skipped']}")
    print(f"  Blocked: {report['blocked']}")
    print(f"  Duration: {report['duration_seconds']}s")
    print()

    for detail in report["details"]:
        icon = "PASS" if detail["result"] == "passed" else "FAIL" if detail["result"] == "failed" else "SKIP"
        print(f"  [{icon}] {detail['name']} ({detail['duration']}s)")
        if detail.get("error"):
            print(f"         Error: {detail['error']}")

    print()
    if report["failed"] > 0:
        print("FAILED: Some integration scenarios did not pass.")
        return 1
    if report["total"] == 0:
        print("WARNING: No scenarios were executed.")
        return 1
    print("All integration scenarios passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run_verification_matrix())
