# AgentMesh A2A Protocol SDK — Integration Layer
#
# Phase 13, Direction 5: Real Agent Framework Integration.
# This package provides abstract adapter interfaces for integrating AgentMesh
# A2A with popular agent frameworks: CrewAI and AutoGen.
#
# All adapters follow the Provider Layer approach — they wrap AgentMesh SDK
# as a Tool/Plugin within the target framework, requiring zero modifications
# to framework source code.
#
# Usage (conceptual):
#   from agentmesh.a2a.integration import CrewAIAdapter, AutoGenAdapter
#   adapter = CrewAIAdapter(server_url="http://localhost:8080")
#   agent = adapter.create_agent(...)
#
# Package path: agentmesh/a2a/integration/

from .autogen_adapter import (
    A2AAgentDef,
    AutoGenAdapterBase,
    AutoGenAgentConfig,
    ConversationPhase,
    GroupChatConfig,
    MessageReceiveResult,
    MessageSendResult,
    MessageType,
)
from .crewai_adapter import (
    A2AToolDef,
    CardReceiveResult,
    CardSendResult,
    CardStatus,
    CardType,
    CrewAIAdapterBase,
    CrewAIAgentConfig,
)
from .e2e_test import (
    DEFAULT_MATRIX,
    FrameworkType,
    IntegrationTestMatrix,
    IntegrationTestRunner,
    ScenarioResult,
    TestResult,
    TestScenario,
    run_verification_matrix,
)

__all__ = [
    # CrewAI
    "CrewAIAdapterBase",
    "A2AToolDef",
    "CrewAIAgentConfig",
    "CardType",
    "CardStatus",
    "CardSendResult",
    "CardReceiveResult",
    # AutoGen
    "AutoGenAdapterBase",
    "A2AAgentDef",
    "AutoGenAgentConfig",
    "GroupChatConfig",
    "MessageType",
    "MessageSendResult",
    "MessageReceiveResult",
    "ConversationPhase",
    # E2E
    "IntegrationTestMatrix",
    "IntegrationTestRunner",
    "TestScenario",
    "ScenarioResult",
    "FrameworkType",
    "TestResult",
    "DEFAULT_MATRIX",
    "run_verification_matrix",
]
