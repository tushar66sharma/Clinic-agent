"""Thin wrapper over an MCP client session that records every tool call for the trace.

The agent talks to the clinic ONLY through MCP tools. This wrapper:
- turns tool results into dicts (structured content or JSON text),
- turns protocol-level tool errors into the same {"ok": false, ...} shape as handled errors,
- records name, arguments (token redacted), result and duration for every call.
"""

from __future__ import annotations

import json
import time
from typing import Any

from mcp import Client

from ..mcp_server import ADMIN_TOOL_PREFIX


class ToolSession:
    def __init__(self, client: Client) -> None:
        self.client = client
        self.calls: list[dict] = []

    def start_message(self) -> None:
        self.calls = []

    @property
    def tool_names(self) -> list[str]:
        names: list[str] = []
        for c in self.calls:
            if not c["tool"].startswith(ADMIN_TOOL_PREFIX) and c["tool"] not in names:
                names.append(c["tool"])
        return names

    async def call(self, name: str, /, **arguments: Any) -> dict:
        args = {k: v for k, v in arguments.items() if v is not None}
        started = time.perf_counter()
        try:
            raw = await self.client.call_tool(name, args)
            result = _payload(raw)
        except Exception as exc:  # transport failure: keep going, record it
            result = {"ok": False, "error": {"code": "tool_transport_error", "message": str(exc)}}
        if not name.startswith(ADMIN_TOOL_PREFIX):
            self.calls.append({
                "tool": name,
                "args": {k: ("***" if k == "verification_token" else v) for k, v in args.items()},
                "result": result,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            })
        return result


def _payload(raw) -> dict:
    if getattr(raw, "is_error", False):
        text = raw.content[0].text if raw.content else "tool error"
        return {"ok": False, "error": {"code": "tool_rejected_input", "message": text}}
    structured = getattr(raw, "structured_content", None)
    if structured:
        return structured
    try:
        return json.loads(raw.content[0].text)
    except (IndexError, AttributeError, ValueError):
        return {"ok": False, "error": {"code": "unreadable_tool_result", "message": str(raw)[:300]}}
