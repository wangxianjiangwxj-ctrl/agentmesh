"""AgentMesh MCP (Model Context Protocol) — stdio-based tool server.

Provides an MCP server exposing the AgentMesh platform modules as 6
JSON-RPC 2.0 tools over stdio.

Typical usage::

    from agentmesh.mcp import MCPServer

    server = MCPServer()
    server.run()

Or from the CLI::

    python -m agentmesh.mcp._server
"""

from agentmesh.mcp._server import MCPServer

__all__ = ["MCPServer"]
