#!/usr/bin/env python3
"""
AgentMesh CLI — Phase 21 Direction A

Command-line tool for managing the AgentMesh platform.

Usage::

    python -m agentmesh.cli serve --port 8000 --db agentmesh.db
    python -m agentmesh.cli agents
    python -m agentmesh.cli health --host localhost --port 8000
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def _ensure_path() -> None:
    """Ensure both the project root and package root are on sys.path.

    The project root is needed for ``from agentmesh.xxx import...`` imports.
    The ``agentmesh/`` subdirectory is needed for short-form imports used
    by existing agent wrappers.
    """
    pkg_root = Path(__file__).resolve().parent  # .../agentmesh/agentmesh
    project_root = pkg_root.parent  # .../agentmesh
    for p in [str(project_root), str(pkg_root)]:
        if p not in sys.path:
            sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


def _do_serve(args: argparse.Namespace) -> None:
    """Start the A2A Bridge + FastAPI Gateway server."""

    async def _start():
        # Import bridge
        from agentmesh.agents.bridge import AgentMeshBridge

        bridge = AgentMeshBridge(db_path=args.db)
        bridge.start()
        print(f"[agentmesh] A2A Bridge started (db={args.db})")
        print(f"[agentmesh] Registered agents: {bridge.registry.count()}")
        for info in bridge.registry.list_all():
            print(f"  - {info.agent_id}: {info.name} [{', '.join(info.capabilities)}]")

        # Import and start FastAPI
        import uvicorn
        from agentmesh.gateway.app import create_app

        app = create_app()
        print(f"[agentmesh] Gateway listening on {args.host}:{args.port}")
        config = uvicorn.Config(
            app=app,
            host=args.host,
            port=args.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(_start())


# ---------------------------------------------------------------------------
# agents
# ---------------------------------------------------------------------------


def _do_agents(args: argparse.Namespace) -> None:
    """List all registered agents via the A2A Bridge."""

    async def _list():
        from agentmesh.agents.bridge import AgentMeshBridge

        bridge = AgentMeshBridge(db_path=args.db)
        bridge.start()
        print(f"AgentRegistry: {bridge.registry.count()} agent(s) registered")
        print()
        for info in bridge.registry.list_all():
            print(f"  Agent ID   : {info.agent_id}")
            print(f"  Name       : {info.name}")
            print(f"  Capabilities: {', '.join(info.capabilities)}")
            print(f"  DID        : {info.did or '(not set)'}")
            print()
        bridge.shutdown()

    asyncio.run(_list())


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def _do_health(args: argparse.Namespace) -> None:
    """Check service health via HTTP."""
    import httpx

    url = f"http://{args.host}:{args.port}/api/v1/health"
    try:
        resp = httpx.get(url, timeout=5.0)
        data = resp.json()
        if data.get("status") == "ok":
            print(f"[OK] Gateway is healthy at {url}")
            print(f"     version: {data.get('version', 'unknown')}")
        else:
            print(f"[WARN] Unexpected response: {data}")
    except httpx.ConnectError:
        print(f"[FAIL] Cannot connect to {url}  — is the server running?")
    except Exception as exc:
        print(f"[FAIL] Health check error: {exc}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point for the AgentMesh CLI.

    Parses command-line arguments and dispatches to the appropriate
    subcommand handler (serve, agents, health).

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).
    """
    _ensure_path()

    parser = argparse.ArgumentParser(
        prog="agentmesh",
        description="AgentMesh CLI — manage the agent economy platform",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- serve -----------------------------------------------------------
    serve_parser = subparsers.add_parser("serve", help="Start the Gateway server")
    serve_parser.add_argument(
        "--port", type=int, default=8000, help="Gateway HTTP port (default: 8000)"
    )
    serve_parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Bind address (default: 0.0.0.0)"
    )
    serve_parser.add_argument(
        "--db", type=str, default=":memory:", help="SQLite database path"
    )

    # -- agents ----------------------------------------------------------
    agents_parser = subparsers.add_parser("agents", help="List all registered agents")
    agents_parser.add_argument(
        "--db", type=str, default=":memory:", help="SQLite database path"
    )

    # -- health ----------------------------------------------------------
    health_parser = subparsers.add_parser("health", help="Check gateway health")
    health_parser.add_argument(
        "--host", type=str, default="localhost", help="Gateway host (default: localhost)"
    )
    health_parser.add_argument(
        "--port", type=int, default=8000, help="Gateway port (default: 8000)"
    )

    args = parser.parse_args(argv)

    if args.command == "serve":
        _do_serve(args)
    elif args.command == "agents":
        _do_agents(args)
    elif args.command == "health":
        _do_health(args)


if __name__ == "__main__":
    main()
