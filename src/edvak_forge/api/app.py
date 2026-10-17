"""HTTP API for the web dashboard (FastAPI).

The API keeps ONE in-process MCP connection to the clinic tool server for its lifetime, so the
dashboard sees a live, shared clinic state: bookings made by one request are visible to the
next. Agent work is serialised with a lock, because the clinic state and the simulated clock are
shared.

Security (docs/security.md):
- AI provider keys stay on the server; the browser never sees them.
- If DEMO_ACCESS_TOKEN is set, every endpoint that spends AI quota or changes state requires the
  header `X-Access-Token`. Read-only endpoints stay open.
- CORS origins come from ALLOWED_ORIGINS (comma-separated).
- Input sizes are bounded; report names are checked against the real folder list.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp import Client
from pydantic import BaseModel, Field

from ..agent.executor import MessageProcessor
from ..agent.tools_client import ToolSession
from ..clinic.scheduling import weekday_name
from ..config import REPO_ROOT, load_settings
from ..llm.base import LLMError
from ..llm.factory import build_llm_client
from ..mcp_server import build_server

log = logging.getLogger("edvak_forge.api")

MESSAGE_SETS = {
    "sample": ("messages_sample.json", "labels_sample.json"),
    "extra": ("messages_extra.json", "labels_extra.json"),
}
REPORTS_DIR = REPO_ROOT / "reports"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


# ---------------------------------------------------------------- request bodies

class NewMessage(BaseModel):
    channel: Literal["sms", "portal", "email"] = "sms"
    from_name: str = Field(min_length=1, max_length=120)
    from_contact: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=1, max_length=2000)
    stated_dob: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    received_at: str | None = Field(default=None, max_length=40,
                                    description="ISO datetime; default today 08:00 clinic time")


class RunRequest(BaseModel):
    set: Literal["sample", "extra"] = "sample"
    ids: list[str] | None = Field(default=None, max_length=100)
    reset_first: bool = True


# ---------------------------------------------------------------- application state

class State:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.tools: ToolSession | None = None
        self.holder: dict | None = None
        self.processor: MessageProcessor | None = None
        self.llm = None
        self.llm_error: str | None = None
        self.lock = asyncio.Lock()
        self.processed: dict[str, dict] = {}  # message id -> {message, result, trace}
        self.jobs: dict[str, dict] = {}
        self.custom_counter = 0
        self.stack = AsyncExitStack()


def create_app(llm_factory=build_llm_client) -> FastAPI:
    state = State()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        server, holder = build_server()
        client = await state.stack.enter_async_context(Client(server))
        state.tools, state.holder = ToolSession(client), holder
        try:
            state.llm = llm_factory()
        except LLMError as exc:
            state.llm, state.llm_error = None, str(exc)
            log.warning("AI provider not configured, running without a model: %s", exc)
        state.processor = MessageProcessor(state.tools, state.llm, state.settings.today)
        await state.processor.clinic_info()
        yield
        await state.stack.aclose()

    app = FastAPI(title="Edvak Forge API", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.edvak = state

    origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
               if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Access-Token"])

    # ------------------------------------------------------------ error format

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
                  for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_input", "message": "Some fields are invalid.", "fields": fields}})

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": {
            "code": "internal_error", "message": "Something went wrong on the server."}})

    def require_token(x_access_token: str | None = Header(default=None)) -> None:
        expected = os.getenv("DEMO_ACCESS_TOKEN", "")
        if expected and not hmac.compare_digest(x_access_token or "", expected):
            raise HTTPException(401, {"code": "access_token_required",
                                      "message": "This action needs the access token."})

    # ------------------------------------------------------------ read-only endpoints

    @app.get("/api/health")
    async def health():
        llm = state.llm
        return {
            "status": "ok",
            "today": state.settings.today.isoformat(),
            "ai": {"configured": llm is not None, "provider": getattr(llm, "provider", None),
                   "models": {r: llm.model_for(r) for r in ("analysis", "reply")} if llm else None,
                   "error": state.llm_error},
            "access_token_required": bool(os.getenv("DEMO_ACCESS_TOKEN")),
            "busy": state.lock.locked(),
        }

    @app.get("/api/clinic")
    async def clinic():
        return await state.processor.clinic_info()

    @app.get("/api/inbox/{set_name}")
    async def inbox(set_name: str):
        if set_name not in MESSAGE_SETS:
            raise HTTPException(404, {"code": "unknown_set", "message": f"No message set {set_name!r}."})
        messages = _load(MESSAGE_SETS[set_name][0])
        return {"set": set_name, "messages": [
            {**m, "processed": state.processed.get(m["id"], {}).get("result")} for m in messages]}

    @app.get("/api/results")
    async def results():
        items = sorted(state.processed.values(), key=lambda x: x["processed_at"], reverse=True)
        return {"items": items}

    @app.get("/api/results/{message_id}")
    async def result(message_id: str):
        item = state.processed.get(message_id)
        if item is None:
            raise HTTPException(404, {"code": "not_processed",
                                      "message": f"{message_id} has not been processed yet."})
        return item

    @app.get("/api/queues")
    async def queues():
        async with state.lock:
            return await state.tools.call("admin_get_run_log")

    @app.get("/api/schedule")
    async def schedule(day: str | None = None):
        try:
            d = date.fromisoformat(day) if day else state.settings.today
        except ValueError:
            raise HTTPException(422, {"code": "invalid_date", "message": "day must be YYYY-MM-DD."}) from None
        svc = state.holder["service"]
        repo = svc.repo
        open_info = svc.check_clinic_open(d.isoformat())
        changed = {c["appointment_id"] for c in svc.log.appointment_changes}
        providers = []
        for p in repo.clinic.providers:
            appts = sorted((a for a in repo.appointments if a.provider == p.id and a.date == d),
                           key=lambda a: a.start)
            providers.append({
                "id": p.id, "name": p.name,
                "on_leave": p.id in open_info.get("providers_on_leave", []),
                "appointments": [{
                    "appointment_id": a.id, "start": a.start, "end": a.end,
                    "visit_type": a.visit_type, "status": a.status, "patient_id": a.patient_id,
                    "patient_name": (repo.patient(a.patient_id).name if repo.patient(a.patient_id) else None),
                    "changed_this_session": a.id in changed,
                } for a in appts],
            })
        return {"date": d.isoformat(), "weekday": weekday_name(d), "open": open_info["open"],
                "closed_reason": open_info["closed_reason"], "providers": providers,
                "prev": (d - timedelta(days=1)).isoformat(), "next": (d + timedelta(days=1)).isoformat()}

    @app.get("/api/reports")
    async def reports():
        items = []
        for folder in _report_folders():
            ev = json.loads((folder / "eval.json").read_text(encoding="utf-8"))
            items.append({"name": folder.name, "headline": ev["headline"]})
        return {"items": items}

    @app.get("/api/reports/{name}")
    async def report(name: str):
        folder = next((f for f in _report_folders() if f.name == name), None)
        if folder is None:  # also blocks path traversal: only real folder names match
            raise HTTPException(404, {"code": "unknown_report", "message": f"No report {name!r}."})
        ev = json.loads((folder / "eval.json").read_text(encoding="utf-8"))
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
        return {"name": name, "evaluation": ev, "summary": summary}

    @app.get("/api/runs/{job_id}")
    async def run_status(job_id: str):
        job = state.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, {"code": "unknown_job", "message": "No such run."})
        return job

    # ------------------------------------------------------------ endpoints that act

    @app.post("/api/messages/process", dependencies=[Depends(require_token)])
    async def process_message(body: NewMessage):
        if state.lock.locked():
            raise HTTPException(409, {"code": "busy", "message": "The agent is busy with a batch run. "
                                                                 "Try again when it finishes."})
        state.custom_counter += 1
        message = {
            "id": f"C{state.custom_counter:03d}",
            "received_at": body.received_at or f"{state.settings.today.isoformat()}T08:00:00-06:00",
            "channel": body.channel, "from_name": body.from_name.strip(),
            "from_contact": body.from_contact.strip(), "body": body.body.strip(),
        }
        if body.stated_dob:
            message["stated_dob"] = body.stated_dob
        try:
            datetime.fromisoformat(message["received_at"])
        except ValueError:
            raise HTTPException(422, {"code": "invalid_input", "message": "received_at must be ISO."}) from None
        async with state.lock:
            return await _process(state, message)

    @app.post("/api/runs", dependencies=[Depends(require_token)])
    async def start_run(req: RunRequest):
        if state.lock.locked():
            raise HTTPException(409, {"code": "busy", "message": "A run is already in progress."})
        messages = _load(MESSAGE_SETS[req.set][0])
        if req.ids:
            wanted = set(req.ids)
            messages = [m for m in messages if m["id"] in wanted]
        if not messages:
            raise HTTPException(422, {"code": "no_messages", "message": "No matching messages."})
        job_id = uuid.uuid4().hex[:12]
        state.jobs[job_id] = {"id": job_id, "set": req.set, "status": "running", "total": len(messages),
                              "done": 0, "current": None, "started_at": time.time(),
                              "finished_at": None, "error": None, "result_ids": []}
        asyncio.create_task(_run_job(state, job_id, messages, req.reset_first))
        return state.jobs[job_id]

    @app.post("/api/state/reset", dependencies=[Depends(require_token)])
    async def reset():
        if state.lock.locked():
            raise HTTPException(409, {"code": "busy", "message": "Wait for the current run to finish."})
        async with state.lock:
            await state.tools.call("admin_reset_state")
            state.processed.clear()
        return {"ok": True}

    # ------------------------------------------------------------ the dashboard itself

    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, {"code": "not_found", "message": "Unknown API route."})
            candidate = (FRONTEND_DIST / path).resolve()
            if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


# ---------------------------------------------------------------- helpers

async def _process(state: State, message: dict) -> dict:
    result, trace = await state.processor.process(message)
    item = {"message": message, "result": result.model_dump(), "trace": trace,
            "processed_at": time.time()}
    state.processed[message["id"]] = item
    return item


async def _run_job(state: State, job_id: str, messages: list[dict], reset_first: bool) -> None:
    job = state.jobs[job_id]
    try:
        async with state.lock:
            if reset_first:
                await state.tools.call("admin_reset_state")
                state.processed.clear()
            for m in messages:
                job["current"] = m["id"]
                await _process(state, m)
                job["done"] += 1
                job["result_ids"].append(m["id"])
        job["status"] = "finished"
    except Exception as exc:  # the job must always end in a visible state
        log.exception("run %s failed", job_id)
        job["status"], job["error"] = "failed", str(exc)
    finally:
        job["current"], job["finished_at"] = None, time.time()


def _load(filename: str) -> list[dict]:
    return json.loads((REPO_ROOT / "data" / filename).read_text(encoding="utf-8"))


def _report_folders() -> list[Path]:
    if not REPORTS_DIR.exists():
        return []
    return sorted(f for f in REPORTS_DIR.iterdir() if f.is_dir() and (f / "eval.json").exists())


app = create_app()
