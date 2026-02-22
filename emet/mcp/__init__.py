"""MCP (Model Context Protocol) server for Project Emet.

Exposes Emet's investigative capabilities as MCP tools that any
compatible AI agent (Claude, GPT, LangChain, Cursor, etc.) can call.

Architecture inspired by mcp-memory-service (Apache 2.0):
  - Typed tool definitions with input schemas
  - Resource endpoints for investigation state
  - JSON-RPC 2.0 over stdio/HTTP transport

Usage::

    from emet.mcp.server import EmetMCPServer

    server = EmetMCPServer()
    await server.run_stdio()  # or server.run_http(port=9400)
"""

from emet.mcp.tools import EMET_TOOLS, EmetToolExecutor
from emet.mcp.resources import EmetResourceProvider
from emet.mcp.server import EmetMCPServer

__all__ = [
    "EMET_TOOLS",
    "EmetToolExecutor",
    "EmetResourceProvider",
    "EmetMCPServer",
]
