# Troubleshooting

Common problems and their fixes. Deployment-specific problems are in [deployment.md](deployment.md#troubleshooting-deployments). AI-provider problems are also covered in [ai-integration.md](ai-integration.md#troubleshooting).

## Setup

| Symptom | Cause | Fix |
|---|---|---|
| `python` not found, or the wrong version | Python 3.11+ not installed or not on PATH | Install Python 3.12 from python.org; on Windows tick "Add to PATH" |
| `.venv\Scripts\python` not found | Virtual environment not created, or you're on macOS/Linux | Run `python -m venv .venv`; on macOS/Linux use `.venv/bin/python` |
| `ModuleNotFoundError: edvak_forge` | Package not installed into the venv | `.venv\Scripts\python -m pip install -e ".[dev]"` |
| `ModuleNotFoundError: mcp.server.fastmcp` in your own code | MCP SDK v2 renamed FastMCP to `MCPServer` | Use `from mcp.server import MCPServer` (the project pins `mcp>=2.3,<3`) |
| `npm` not found | Node.js not installed | Install Node.js 22 LTS from nodejs.org |
| Garbled characters (`'charmap' codec can't encode`) printing Spanish text on Windows | The console uses a legacy code page | Set `PYTHONIOENCODING=utf-8`, or use Windows Terminal |

## Running the agent

| Symptom | Cause | Fix |
|---|---|---|
| `LLM configuration error: GROQ_API_KEY is not set` | No `.env`, or key missing | Copy `.env.example` to `.env` and add the key |
| Long pauses of about 1 minute during a run | Client throttle waiting for the free per-minute token budget | Normal. A full run takes about 8 minutes |
| Some results routed to `front_desk` with path `fallback_no_model` | The AI call failed after retries (rate limit or outage) | Check `llm_error` in `runs/latest/traces.json`. Wait for the limit to reset, or switch provider |
| Results don't change after editing a prompt | They do: the cache key includes the full prompt. If they still don't, the change didn't affect the request | Set `LLM_CACHE=0` to force fresh calls |
| Results unexpectedly identical to last time | Cached responses reused (`+N cached` in the output) | Intended; set `LLM_CACHE=0` for a fresh run |
| `--transport stdio` hangs | The MCP server subprocess failed to start | Run `python -m edvak_forge.mcp_server` directly to see its error; or use `--transport inprocess` |

## Web dashboard

| Symptom | Cause | Fix |
|---|---|---|
| Dashboard says "Cannot reach the server" | API not running | Start it: `.venv\Scripts\python -m edvak_forge.api` |
| `npm run dev` page loads but API calls fail | API not on port 8000 | The Vite dev server forwards `/api` to `localhost:8000`; start the API there |
| Opening http://localhost:8000 shows JSON 404 instead of the dashboard | Dashboard not built | `cd frontend && npm install && npm run build`, then restart the API |
| "The agent is busy" (409) | A batch run is in progress | Wait for it to finish; the progress bar shows status |
| "This action needs the access token" | `DEMO_ACCESS_TOKEN` is set on the server | Enter it on the **System** page |
| Processed results disappear | Server restarted; state is in memory by design | Process again. Use **Reset clinic data** for a clean start |

## Tests

| Symptom | Cause | Fix |
|---|---|---|
| Tests make network calls or are slow | They shouldn't: tests use a fake model | Make sure you run `pytest` from the project folder; set `LLM_CACHE=0` to avoid touching the cache |
| `scripts/ui_smoke.py` fails to start | Playwright or Chromium not installed, or API not running | `pip install -e ".[ui-test]"` then `python -m playwright install chromium`; start the API and build the dashboard first |
| Evaluation says `Missing runs/latest/results.json` | No agent run yet | Run `python -m edvak_forge.evaluation --agent` |
