"""Run the agent over an inbox file.

    python -m edvak_forge.agent.runner                          # all 40 sample messages
    python -m edvak_forge.agent.runner --only M003,M014         # a subset
    python -m edvak_forge.agent.runner --messages my_inbox.json # new, unseen messages
    python -m edvak_forge.agent.runner --transport inprocess    # skip the subprocess

Outputs go to runs/<timestamp>/ and are copied to runs/latest/:
    results.json   one result per message, in the brief's format
    traces.json    per-message path, analysis, facts and every tool call (for debugging)
    run_log.json   queue tickets, refill requests, reply drafts, flags, appointment changes
    summary.json   counts, timing, token usage, provider and model
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from mcp import Client, StdioServerParameters

from ..config import REPO_ROOT, load_settings
from ..llm.base import LLMClient, LLMError
from ..llm.factory import build_llm_client
from ..mcp_server import build_server
from .executor import MessageProcessor
from .tools_client import ToolSession

log = logging.getLogger("edvak_forge.runner")


@asynccontextmanager
async def open_tools(transport: str = "stdio"):
    """Connect to the MCP tool server: as a subprocess (stdio) or in the same process."""
    if transport == "stdio":
        params = StdioServerParameters(command=sys.executable,
                                       args=["-m", "edvak_forge.mcp_server"])
        client = Client(params, read_timeout_seconds=60)
    else:
        server, _ = build_server()
        client = Client(server)
    async with client:
        yield ToolSession(client)


async def run_messages(messages: list[dict], llm: LLMClient | None, *, transport: str = "stdio",
                       on_result=None) -> dict:
    settings = load_settings()
    results, traces = [], []
    started = time.perf_counter()
    async with open_tools(transport) as tools:
        await tools.call("admin_reset_state")
        processor = MessageProcessor(tools, llm, settings.today)
        await processor.clinic_info()  # fetched once per run, not per message
        for i, raw in enumerate(messages, 1):
            t0 = time.perf_counter()
            try:
                result, trace = await processor.process(raw)
            except Exception as exc:  # last-resort safety net: record and continue
                log.exception("message %s crashed", raw.get("id"))
                result, trace = _crash_result(raw, exc), {"id": raw.get("id"), "crash": repr(exc)}
            trace["seconds"] = round(time.perf_counter() - t0, 2)
            results.append(result.model_dump() if hasattr(result, "model_dump") else result)
            traces.append(trace)
            log.info("[%d/%d] %s urgency=%s actions=%s (%.1fs)", i, len(messages), raw.get("id"),
                     results[-1]["urgency"], results[-1]["actions"], trace["seconds"])
            if on_result:
                on_result(results[-1], trace)
        run_log = await tools.call("admin_get_run_log")
    return {
        "results": results, "traces": traces, "run_log": run_log,
        "summary": {
            "messages": len(messages),
            "seconds": round(time.perf_counter() - started, 1),
            "provider": getattr(llm, "provider", None),
            "models": {r: llm.model_for(r) for r in ("analysis", "reply")} if llm else None,
            "usage": llm.usage.to_dict() if llm else None,
            "paths": _count(t.get("path", "crash") for t in traces),
            "today": settings.today.isoformat(),
            "transport": transport,
        },
    }


def _crash_result(raw: dict, exc: Exception) -> dict:
    """If something unexpected breaks, the message still goes to a human, never silently dropped."""
    return {"id": raw.get("id"), "patient_id": None, "intents": ["other"], "urgency": "urgent",
            "actions": ["route_to_front_desk"], "routed_to": ["front_desk"], "tool_calls": [],
            "reply_draft": "Thank you for your message. A member of our team will get back to you."}


def _count(items) -> dict:
    out: dict = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out


def write_outputs(output: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("results", "traces", "run_log", "summary"):
        (out_dir / f"{name}.json").write_text(
            json.dumps(output[name], indent=2, ensure_ascii=False), encoding="utf-8")
    latest = out_dir.parent / "latest"
    if latest.resolve() != out_dir.resolve():
        shutil.rmtree(latest, ignore_errors=True)
        shutil.copytree(out_dir, latest)
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Edvak Forge front-desk agent.")
    parser.add_argument("--messages", type=Path, default=REPO_ROOT / "data" / "messages_sample.json")
    parser.add_argument("--only", help="Comma-separated message ids to process")
    parser.add_argument("--out", type=Path, help="Output directory (default runs/<timestamp>)")
    parser.add_argument("--transport", choices=["stdio", "inprocess"], default="stdio")
    parser.add_argument("--no-llm", action="store_true",
                        help="Run without a model (guard + fallback only), for testing the pipeline")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    messages = json.loads(args.messages.read_text(encoding="utf-8"))
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        messages = [m for m in messages if m["id"] in wanted]
    if not messages:
        print("No messages to process.", file=sys.stderr)
        return 1

    llm = None
    if not args.no_llm:
        try:
            llm = build_llm_client()
        except LLMError as exc:
            print(f"LLM configuration error: {exc}", file=sys.stderr)
            return 2

    output = asyncio.run(run_messages(messages, llm, transport=args.transport))
    out_dir = args.out or REPO_ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    write_outputs(output, out_dir)
    s = output["summary"]
    print(f"\nProcessed {s['messages']} messages in {s['seconds']}s -> {out_dir}")
    if s["usage"]:
        u = s["usage"]
        print(f"Model requests: {u['requests']} (+{u['cache_hits']} cached), "
              f"tokens: {u['total_tokens']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
