"""MCP (Model Context Protocol) server for AgentMesh Platform.

Implements a JSON-RPC 2.0 server over stdio that exposes 6 tools backed
by the AgentMesh platform core modules:

  1. identity_register  -- register an agent identity
  2. task_create        -- create a marketplace task
  3. task_assign        -- assign a task to an executor
  4. escrow_deposit     -- deposit points into an escrow account
  5. evidence_submit    -- record an evidence-chain entry
  6. reputation_score   -- query an agent's reputation score

Usage:
    python -m agentmesh.mcp._server
    # then send JSON-RPC 2.0 messages on stdin
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Ensure platform modules are importable (they use bare ``from identity`` etc.)
# ---------------------------------------------------------------------------
_platform_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "platform")
)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

# Import platform modules *after* path fix
from db_schema import SCHEMA_SQL  # type: ignore[import-untyped]  # noqa: E402
from escrow import EscrowService  # type: ignore[import-untyped]  # noqa: E402
from evidence_chain import EvidenceChainService  # type: ignore[import-untyped]  # noqa: E402
from identity import IdentityService  # type: ignore[import-untyped]  # noqa: E402
from reputation import ReviewService  # type: ignore[import-untyped]  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JSON_RPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "agentmesh-mcp"
SERVER_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Tool definitions  (JSON Schema input_schema)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "identity_register",
        "description": "Register a new agent identity with an Ed25519 key pair",
        "inputSchema": {
            "type": "object",
            "properties": {
                "display_name": {
                    "type": "string",
                    "description": "Human-readable alias for the agent",
                },
                "capabilities": {
                    "type": "string",
                    "description": "Optional JSON-encoded capabilities metadata",
                },
            },
            "required": ["display_name"],
        },
    },
    {
        "name": "task_create",
        "description": "Create a new task in the marketplace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Task title",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed task description",
                },
                "reward": {
                    "type": "integer",
                    "description": "Escrow reward amount in platform points",
                    "default": 0,
                },
                "deadline": {
                    "type": "string",
                    "description": "ISO 8601 deadline timestamp (optional)",
                },
            },
            "required": ["title", "description"],
        },
    },
    {
        "name": "task_assign",
        "description": "Assign an executor to an open task",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "UUID of the task to assign",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID of the executor",
                },
            },
            "required": ["task_id", "agent_id"],
        },
    },
    {
        "name": "escrow_deposit",
        "description": "Deposit points into an agent's escrow account",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task identifier (for transaction tracking)",
                },
                "amount": {
                    "type": "integer",
                    "description": "Number of points to deposit",
                },
                "depositor": {
                    "type": "string",
                    "description": "Agent ID of the depositor",
                },
            },
            "required": ["task_id", "amount", "depositor"],
        },
    },
    {
        "name": "evidence_submit",
        "description": "Submit an evidence-chain entry for a task",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task identifier this evidence belongs to",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID of the submitter",
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description stored in the evidence payload",
                },
            },
            "required": ["task_id", "agent_id", "description"],
        },
    },
    {
        "name": "reputation_score",
        "description": "Query the reputation score for an agent",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID to query",
                },
            },
            "required": ["agent_id"],
        },
    },
]


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def make_request(id_: Any, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request object.

    Args:
        id_: Request identifier (any JSON-valid value).
        method: The method name to invoke.
        params: Parameters dict.

    Returns:
        A JSON-RPC 2.0 request dict.
    """
    return {
        "jsonrpc": JSON_RPC_VERSION,
        "id": id_,
        "method": method,
        "params": params,
    }


def make_success(id_: Any, result: Any) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 success response.

    Args:
        id_: Request identifier echoed from the request.
        result: Result value (any JSON-serialisable object).

    Returns:
        A JSON-RPC 2.0 success response dict.
    """
    return {
        "jsonrpc": JSON_RPC_VERSION,
        "id": id_,
        "result": result,
    }


def make_error(
    id_: Any,
    code: int,
    message: str,
    data: Any = None,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response.

    Args:
        id_: Request identifier (``None`` for notifications).
        code: Integer error code.
        message: Short human-readable error message.
        data: Optional additional error data.

    Returns:
        A JSON-RPC 2.0 error response dict.
    """
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {
        "jsonrpc": JSON_RPC_VERSION,
        "id": id_,
        "error": err,
    }


# ---------------------------------------------------------------------------
# MCPServer
# ---------------------------------------------------------------------------

class MCPServer:
    """MCP (Model Context Protocol) server for AgentMesh.

    Communicates over stdio using JSON-RPC 2.0 framing (one object per
    line).  Maintains a shared SQLite database and lazy-initialised
    service instances.

    Args:
        db_path: Filesystem path to the SQLite database.  Defaults to
            an auto-generated temp file that persists for the lifetime
            of the process.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path: str = db_path or self._default_db_path()
        self._conn: sqlite3.Connection | None = None
        self._identity_svc: IdentityService | None = None
        self._escrow_svc: EscrowService | None = None
        self._evidence_svc: EvidenceChainService | None = None
        self._review_svc: ReviewService | None = None
        self._request_id: Any = None

    # -- lifecycle ---------------------------------------------------------

    @staticmethod
    def _default_db_path() -> str:
        """Return a temporary file path for the SQLite database.

        Returns:
            An absolute path to a new temporary ``.db`` file.
        """
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        return f.name

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy-initialised shared database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(SCHEMA_SQL)
            self._conn.commit()
        return self._conn

    @property
    def identity_service(self) -> IdentityService:
        """Lazy-initialised IdentityService.

        Uses the same database file as the shared connection.
        """
        if self._identity_svc is None:
            self._identity_svc = IdentityService(self._db_path)
            self._identity_svc.conn  # trigger table creation
        return self._identity_svc

    @property
    def escrow_service(self) -> EscrowService:
        """Lazy-initialised EscrowService."""
        if self._escrow_svc is None:
            self._escrow_svc = EscrowService(
                db_conn=self.conn,
                identity_svc=self.identity_service,
            )
        return self._escrow_svc

    @property
    def evidence_service(self) -> EvidenceChainService:
        """Lazy-initialised EvidenceChainService."""
        if self._evidence_svc is None:
            self._evidence_svc = EvidenceChainService(
                identity_svc=self.identity_service,
                db_conn=self.conn,
            )
        return self._evidence_svc

    @property
    def review_service(self) -> ReviewService:
        """Lazy-initialised ReviewService."""
        if self._review_svc is None:
            self._review_svc = ReviewService(
                db_conn=self.conn,
                identity_svc=self.identity_service,
                evidence_svc=self.evidence_service,
            )
        return self._review_svc

    # -- request dispatch --------------------------------------------------

    def handle_line(self, line: str) -> str | None:
        """Parse and handle a single JSON-RPC message.

        Args:
            line: Raw JSON string from stdin.

        Returns:
            A JSON-RPC response string, or ``None`` if there is none.
        """
        line = line.strip()
        if not line:
            return None

        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            return json.dumps(make_error(None, -32700, "Parse error", str(exc)))

        method = msg.get("method", "")
        params = msg.get("params", {})
        req_id = msg.get("id")

        handler = self._get_handler(method)
        if handler is None:
            return json.dumps(
                make_error(req_id, -32601, f"Method not found: {method}")
            )

        try:
            result = handler(req_id, params)
            return json.dumps(make_success(req_id, result))
        except Exception as exc:
            return json.dumps(
                make_error(req_id, -32603, f"Internal error: {exc}", str(exc))
            )

    def _get_handler(self, method: str) -> Callable | None:
        """Resolve a JSON-RPC method to its handler.

        Args:
            method: The method name string.

        Returns:
            The bound handler method, or ``None`` if unknown.
        """
        handlers: dict[str, str] = {
            "initialize": "_handle_initialize",
            "ping": "_handle_ping",
            "tools/list": "_handle_tools_list",
            "tools/call": "_handle_tools_call",
        }
        attr = handlers.get(method)
        if attr is None:
            return None
        return getattr(self, attr)

    # -- MCP protocol handlers ---------------------------------------------

    def _handle_initialize(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle the MCP ``initialize`` request.

        Returns server capabilities and protocol info.

        Args:
            req_id: Request identifier (unused).
            params: Parameters dict (unused).

        Returns:
            An ``InitializeResult`` dict with protocol version,
            server info, and capabilities.
        """
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        }

    def _handle_ping(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle the MCP ``ping`` request.

        Args:
            req_id: Request identifier (unused).
            params: Parameters dict (unused).

        Returns:
            An empty dict as a health-check response.
        """
        return {}

    def _handle_tools_list(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle the MCP ``tools/list`` request.

        Args:
            req_id: Request identifier (unused).
            params: Parameters dict (unused).

        Returns:
            A dict with a ``tools`` array of tool definitions.
        """
        return {"tools": TOOLS}

    def _handle_tools_call(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> Any:
        """Handle the MCP ``tools/call`` request.

        Dispatches to the appropriate tool implementation based on
        the ``name`` parameter.

        Args:
            req_id: Request identifier (unused).
            params: Parameters dict with ``name`` (tool name) and
                ``arguments`` (tool input).

        Returns:
            A ``ToolCallResult`` dict with a ``content`` array
            containing the tool output.

        Raises:
            ValueError: If the tool name is unknown or arguments are
                invalid.
        """
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        tool_map: dict[str, Callable] = {
            "identity_register": self._tool_identity_register,
            "task_create": self._tool_task_create,
            "task_assign": self._tool_task_assign,
            "escrow_deposit": self._tool_escrow_deposit,
            "evidence_submit": self._tool_evidence_submit,
            "reputation_score": self._tool_reputation_score,
        }
        handler = tool_map.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")

        result = handler(arguments)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2),
                }
            ],
        }

    # -- tool implementations ----------------------------------------------

    def _tool_identity_register(
        self,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Register a new agent identity.

        Args:
            args: Must contain ``display_name`` and optionally
                ``capabilities``.

        Returns:
            A dict with ``agent_id``, ``did``, ``name``, and
            ``public_key``.
        """
        display_name = args["display_name"]
        capabilities = args.get("capabilities", "")
        agent = self.identity_service.register(
            name=display_name,
            auth_token="",
            metadata={"capabilities": capabilities} if capabilities else {},
        )
        return {
            "agent_id": agent["id"],
            "did": agent["did"],
            "name": agent["name"],
            "public_key": agent["public_key"],
        }

    def _tool_task_create(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new marketplace task.

        Inserts directly into the shared ``tasks`` table because the
        platform does not expose a dedicated task-service class.

        Args:
            args: Must contain ``title``, ``description``, and
                optionally ``reward`` and ``deadline``.

        Returns:
            A dict with ``task_id``, ``title``, ``status``, and
            ``created_at``.
        """
        title = args["title"]
        description = args.get("description", "")
        reward = args.get("reward", 0)
        deadline = args.get("deadline", "")

        task_id = uuid.uuid4().hex
        with self.conn:
            self.conn.execute(
                """INSERT INTO tasks (id, publisher_id, title, description,
                                      escrow_amount, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'open', datetime('now'), datetime('now'))""",
                (task_id, "system", title, description, reward),
            )
            if deadline:
                self.conn.execute(
                    "UPDATE tasks SET metadata = ? WHERE id = ?",
                    (json.dumps({"deadline": deadline}), task_id),
                )

        return {
            "task_id": task_id,
            "title": title,
            "status": "open",
            "reward": reward,
            "created_at": datetime.now().isoformat(),
        }

    def _tool_task_assign(self, args: dict[str, Any]) -> dict[str, Any]:
        """Assign an executor to an open task.

        Args:
            args: Must contain ``task_id`` and ``agent_id``.

        Returns:
            A dict with ``task_id``, ``executor_id``, and ``status``.

        Raises:
            ValueError: If the task is not found or not in ``open``
                status.
        """
        task_id = args["task_id"]
        agent_id = args["agent_id"]

        row = self.conn.execute(
            "SELECT id, status FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Task not found: {task_id}")
        if row["status"] != "open":
            raise ValueError(
                f"Task {task_id} has status '{row['status']}', expected 'open'"
            )

        with self.conn:
            self.conn.execute(
                """UPDATE tasks
                   SET executor_id = ?, status = 'assigned', updated_at = datetime('now')
                   WHERE id = ?""",
                (agent_id, task_id),
            )

        return {
            "task_id": task_id,
            "executor_id": agent_id,
            "status": "assigned",
        }

    def _tool_escrow_deposit(self, args: dict[str, Any]) -> dict[str, Any]:
        """Deposit points into an agent's escrow account.

        Args:
            args: Must contain ``task_id``, ``amount``, and
                ``depositor``.

        Returns:
            A dict with ``agent_id``, ``balance``, ``frozen``, and
            ``available``.
        """
        task_id = args["task_id"]
        amount = args["amount"]
        depositor = args["depositor"]

        self.escrow_service.ensure_account(depositor)
        self.escrow_service.deposit(depositor, amount)
        balance = self.escrow_service.get_balance(depositor)

        return {
            "agent_id": depositor,
            "balance": balance["balance"],
            "frozen": balance["frozen"],
            "available": balance["available"],
            "task_id": task_id,
            "deposited": amount,
        }

    def _tool_evidence_submit(self, args: dict[str, Any]) -> dict[str, Any]:
        """Submit an evidence-chain entry for a task.

        Args:
            args: Must contain ``task_id``, ``agent_id``, and
                ``description``.

        Returns:
            A dict with ``entry_id``, ``chain_hash``, and
            ``chain_index``.

        Raises:
            ValueError: If the agent's private key is not available.
        """
        task_id = args["task_id"]
        agent_id = args["agent_id"]
        description = args["description"]

        payload = {
            "description": description,
            "submitted_by": agent_id,
            "task_id": task_id,
        }
        entry = self.evidence_service.record(
            task_id=task_id,
            action="evidence_submit",
            actor_id=agent_id,
            payload=payload,
        )
        return {
            "entry_id": entry.id,
            "chain_hash": entry.chain_hash,
            "chain_index": entry.chain_index,
            "action": entry.action,
        }

    def _tool_reputation_score(self, args: dict[str, Any]) -> dict[str, Any]:
        """Query the reputation score for an agent.

        Args:
            args: Must contain ``agent_id``.

        Returns:
            A dict with ``agent_id``, ``avg_rating``, and
            ``total_reviews``.
        """
        agent_id = args["agent_id"]
        rep = self.review_service.get_reputation(agent_id)
        return {
            "agent_id": agent_id,
            "avg_rating": rep.get("avg_rating", 0.0),
            "total_reviews": rep.get("total_reviews", 0),
        }

    # -- stdio run loop ----------------------------------------------------

    def run(self) -> None:
        """Start the MCP server, reading JSON-RPC requests from stdin.

        Each line of stdin is treated as a separate JSON-RPC request.
        Responses are written to stdout, one per line.
        """
        # Signal readiness: MCP clients expect a stderr message on startup
        sys.stderr.write(f"MCP server started (db: {self._db_path})\n")
        sys.stderr.flush()

        for line in sys.stdin:
            response = self.handle_line(line)
            if response is not None:
                sys.stdout.write(response + "\n")
                sys.stdout.flush()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server from the command line."""
    db_path = os.environ.get("AGENTMESH_DB_PATH")
    server = MCPServer(db_path=db_path)
    server.run()


if __name__ == "__main__":
    main()
