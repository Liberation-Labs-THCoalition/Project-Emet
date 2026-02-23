"""MCP server for Project Emet.

Implements the Model Context Protocol over stdio and HTTP/SSE
transports using JSON-RPC 2.0.  This is a thin protocol layer that
delegates all real work to EmetToolExecutor and EmetResourceProvider.

Transport options:
  - stdio: For Claude Desktop, Claude Code, Cursor, etc.
  - HTTP/SSE: For team collaboration, web clients, remote agents

Usage::

    # stdio (Claude Desktop config)
    server = EmetMCPServer()
    await server.run_stdio()

    # HTTP (team / remote)
    server = EmetMCPServer()
    await server.run_http(host="0.0.0.0", port=9400)

Reference: mcp-memory-service architecture for MCP protocol patterns.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from typing import Any

from emet.mcp.tools import EMET_TOOLS, EmetToolExecutor
from emet.mcp.resources import EmetResourceProvider

logger = logging.getLogger(__name__)

# MCP protocol version
MCP_PROTOCOL_VERSION = "2024-11-05"

# Server info
SERVER_INFO = {
    "name": "emet-investigative-server",
    "version": "0.10.0",
}

# Server capabilities
SERVER_CAPABILITIES = {
    "tools": {"listChanged": False},
    "resources": {"subscribe": False, "listChanged": False},
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 helpers
# ---------------------------------------------------------------------------


def _jsonrpc_response(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id: Any, code: int, message: str, data: Any = None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": error}


def _jsonrpc_notification(method: str, params: dict | None = None) -> dict:
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return msg


# Error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------


class EmetMCPServer:
    """MCP server exposing Emet investigative capabilities.

    Handles the MCP protocol lifecycle:
      1. initialize → capabilities exchange
      2. tools/list → enumerate available tools
      3. tools/call → execute investigative tools
      4. resources/list → enumerate resources
      5. resources/read → read investigation state
    """

    def __init__(self) -> None:
        self.executor = EmetToolExecutor()
        self.resources = EmetResourceProvider()
        self._initialized = False
        self._session_id = str(uuid.uuid4())

        # Method dispatch table
        self._methods: dict[str, Any] = {
            "initialize": self._handle_initialize,
            "initialized": self._handle_initialized,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
        }

    # --- Protocol handlers ---

    async def _handle_initialize(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle MCP initialize request."""
        client_info = params.get("clientInfo", {})
        logger.info(
            "MCP client connecting: %s %s",
            client_info.get("name", "unknown"),
            client_info.get("version", ""),
        )
        self._initialized = True
        self.resources.session.session_id = self._session_id

        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": SERVER_CAPABILITIES,
            "serverInfo": SERVER_INFO,
        }

    async def _handle_initialized(self, params: dict[str, Any]) -> None:
        """Handle MCP initialized notification (no response)."""
        logger.info("MCP session initialized: %s", self._session_id)
        return None

    async def _handle_ping(self, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def _handle_tools_list(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """List all available tools."""
        return {"tools": self.executor.list_tools()}

    async def _handle_tools_call(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool call."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        logger.info("MCP tool call: %s", tool_name)
        result = await self.executor.execute(tool_name, arguments)

        # Track in session state
        raw = result.get("_raw", {})
        result_count = raw.get("result_count", raw.get("entity_count", 0))
        self.resources.session.record_query(tool_name, arguments, result_count)

        # Add discovered entities to session
        entities = raw.get("entities", [])
        if entities:
            self.resources.session.add_entities(entities)

        # Add alerts to session
        alerts = raw.get("alerts", [])
        if alerts:
            self.resources.session.add_alerts(alerts)

        # Return MCP-formatted result (without _raw)
        return {
            "content": result.get("content", []),
            "isError": result.get("isError", False),
        }

    async def _handle_resources_list(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """List available resources."""
        return {"resources": self.resources.list_resources()}

    async def _handle_resources_read(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Read a resource."""
        uri = params.get("uri", "")
        return await self.resources.read_resource(uri)

    # --- Message routing ---

    async def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Route a JSON-RPC 2.0 message to the appropriate handler."""
        if "jsonrpc" not in message or message.get("jsonrpc") != "2.0":
            return _jsonrpc_error(
                message.get("id"), INVALID_REQUEST, "Not a JSON-RPC 2.0 message"
            )

        method = message.get("method", "")
        params = message.get("params", {})
        msg_id = message.get("id")

        handler = self._methods.get(method)
        if handler is None:
            if msg_id is not None:
                return _jsonrpc_error(msg_id, METHOD_NOT_FOUND, f"Unknown method: {method}")
            return None  # Unknown notification — ignore

        try:
            result = await handler(params)
            if msg_id is None:
                return None  # Notification — no response
            return _jsonrpc_response(msg_id, result)
        except Exception as exc:
            logger.exception("Error handling %s", method)
            if msg_id is not None:
                return _jsonrpc_error(msg_id, INTERNAL_ERROR, str(exc))
            return None

    # --- stdio transport ---

    async def run_stdio(self) -> None:
        """Run MCP server over stdio (for Claude Desktop, Cursor, etc.)."""
        logger.info("Emet MCP server starting on stdio")
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(
            lambda: protocol, sys.stdin.buffer
        )

        writer_transport, writer_protocol = (
            await asyncio.get_event_loop().connect_write_pipe(
                asyncio.streams.FlowControlMixin, sys.stdout.buffer
            )
        )
        writer = asyncio.StreamWriter(
            writer_transport, writer_protocol, None, asyncio.get_event_loop()
        )

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    message = json.loads(line.decode("utf-8").strip())
                except json.JSONDecodeError:
                    response = _jsonrpc_error(None, PARSE_ERROR, "Invalid JSON")
                    await self._write_message(writer, response)
                    continue

                response = await self.handle_message(message)
                if response is not None:
                    await self._write_message(writer, response)

        except asyncio.CancelledError:
            logger.info("MCP server shutting down")
        except Exception:
            logger.exception("MCP server error")

    async def _write_message(
        self, writer: asyncio.StreamWriter, message: dict
    ) -> None:
        """Write a JSON-RPC message to stdout."""
        data = json.dumps(message) + "\n"
        writer.write(data.encode("utf-8"))
        await writer.drain()

    # --- HTTP/SSE transport ---

    async def run_http(self, host: str = "0.0.0.0", port: int = 9400) -> None:
        """Run MCP server over HTTP with SSE support.

        Mounts alongside the existing FastAPI app or as standalone.
        """
        try:
            from fastapi import FastAPI, Request
            from fastapi.responses import JSONResponse
            import uvicorn
        except ImportError:
            logger.error("FastAPI/uvicorn required for HTTP transport")
            return

        app = FastAPI(title="Emet MCP Server", version=SERVER_INFO["version"])

        @app.post("/mcp")
        async def mcp_endpoint(request: Request) -> JSONResponse:
            """JSON-RPC 2.0 endpoint for MCP."""
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    _jsonrpc_error(None, PARSE_ERROR, "Invalid JSON"),
                    status_code=200,
                )

            response = await self.handle_message(body)
            if response is None:
                return JSONResponse({"jsonrpc": "2.0", "result": None}, status_code=200)
            return JSONResponse(response, status_code=200)

        @app.get("/mcp/health")
        async def health() -> dict:
            return {
                "status": "ok",
                "server": SERVER_INFO,
                "session_id": self._session_id,
                "tool_count": len(EMET_TOOLS),
                "entity_count": self.resources.session.entity_count,
            }

        logger.info("Emet MCP server starting on http://%s:%d/mcp", host, port)
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def run_sse(self, host: str = "0.0.0.0", port: int = 9400) -> None:
        """Run MCP server over HTTP/SSE (Model Context Protocol standard).

        SSE transport implements the MCP specification:
          - GET  /sse       → SSE stream for server→client messages
          - POST /messages  → Client→server JSON-RPC messages

        Each client gets a unique session via query param on /messages.
        """
        try:
            import asyncio as _asyncio
            import uuid as _uuid
            from fastapi import FastAPI, Request
            from fastapi.responses import JSONResponse
            from starlette.responses import StreamingResponse
            import uvicorn
        except ImportError:
            logger.error("FastAPI/uvicorn required for SSE transport")
            return

        app = FastAPI(title="Emet MCP Server (SSE)", version=SERVER_INFO["version"])

        # Per-session message queues: session_id → asyncio.Queue
        _sessions: dict[str, _asyncio.Queue] = {}

        @app.get("/sse")
        async def sse_endpoint(request: Request) -> StreamingResponse:
            """SSE stream endpoint.  Sends an 'endpoint' event on connect
            telling the client where to POST messages."""
            session_id = str(_uuid.uuid4())
            queue: _asyncio.Queue = _asyncio.Queue()
            _sessions[session_id] = queue

            messages_url = f"http://{host}:{port}/messages?session_id={session_id}"

            async def event_stream():
                # First event: tell client the messages endpoint
                yield f"event: endpoint\ndata: {messages_url}\n\n"

                try:
                    while True:
                        # Check if client disconnected
                        if await request.is_disconnected():
                            break
                        try:
                            msg = await _asyncio.wait_for(queue.get(), timeout=30.0)
                            import json as _json
                            yield f"event: message\ndata: {_json.dumps(msg)}\n\n"
                        except _asyncio.TimeoutError:
                            # Send keepalive comment
                            yield ": keepalive\n\n"
                finally:
                    _sessions.pop(session_id, None)

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        @app.post("/messages")
        async def messages_endpoint(request: Request) -> JSONResponse:
            """Receive JSON-RPC messages from client, route responses to SSE."""
            session_id = request.query_params.get("session_id", "")
            queue = _sessions.get(session_id)
            if queue is None:
                return JSONResponse(
                    {"error": "Unknown session. Connect to /sse first."},
                    status_code=400,
                )

            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    _jsonrpc_error(None, PARSE_ERROR, "Invalid JSON"),
                    status_code=200,
                )

            response = await self.handle_message(body)
            if response is not None:
                await queue.put(response)

            return JSONResponse({"ok": True}, status_code=202)

        @app.get("/health")
        async def health() -> dict:
            return {
                "status": "ok",
                "transport": "sse",
                "server": SERVER_INFO,
                "active_sessions": len(_sessions),
                "tool_count": len(EMET_TOOLS),
            }

        logger.info("Emet MCP server (SSE) starting on http://%s:%d", host, port)
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """CLI entry point for Emet MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Emet MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9400, help="HTTP port")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    server = EmetMCPServer()
    if args.transport == "http":
        await server.run_http(host=args.host, port=args.port)
    elif args.transport == "sse":
        await server.run_sse(host=args.host, port=args.port)
    else:
        await server.run_stdio()


def cli_main() -> None:
    """Sync CLI entry point for `emet-mcp` command."""
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
