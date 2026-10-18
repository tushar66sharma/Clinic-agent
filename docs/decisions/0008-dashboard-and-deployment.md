# ADR 0008: Web dashboard and free-tier deployment

- **Status:** Accepted
- **Date:** 2026-10-18

## Context

The project rules require a professional, responsive frontend connected to real backend functionality, and a free-tier deployment that a beginner can follow. The brief also asks that the agent be "running and ready to process new messages" during the walkthrough.

## Decisions

**API: FastAPI with one long-lived in-process MCP connection.** The API holds one MCP client connected in-process to the tool server, so every request shares one live clinic state. A booking made from the dashboard appears in the schedule straight away. Agent work is serialised with a lock, because the clinic state and the simulated clock are shared. Blocking AI calls run in worker threads, so health checks stay responsive while the agent waits on rate limits.

**Graceful without a key.** If no AI key is configured, the API still starts. Emergencies are still escalated by the guard, and everything else is handed to staff. The dashboard shows a banner explaining this.

**Access token for actions.** `DEMO_ACCESS_TOKEN`, if set, is required for endpoints that spend AI quota or change state. Viewing stays open. This is a demo safeguard, not real authentication (see security.md).

**Frontend: React + Vite + TypeScript + Tailwind CSS v4, plus lucide icons and React Router.** This is a small, mainstream stack with a static build, so it can be hosted anywhere. A token-based design system lives in `frontend/src/index.css`, with reusable components in `frontend/src/components/`. No component library was added: the screens are simple, and plain Tailwind keeps the bundle around 100 KB gzipped.

**Deployment: one Docker image serving both API and dashboard (Render free web service).** One URL, no CORS, one set of environment variables, and the same image runs locally with `docker run`. Option B (Render API + Vercel dashboard) is documented for people who prefer Vercel.

## Alternatives considered

- **Vercel only (serverless functions).** The agent needs a long-lived MCP session and in-memory state, and a full batch run lasts minutes. That doesn't fit stateless functions with a 300-second cap.
- **Separate frontend and backend as the default.** Two platforms and CORS add steps for a beginner, so it's offered as Option B instead.
- **Server-sent events or WebSockets for batch progress.** Polling every 1.5 seconds is simpler and works through any proxy. Progress granularity is one message, so polling loses nothing.
- **A UI component library (MUI, shadcn/ui).** Heavier, or adds generated code to maintain. The custom set is small.

## Verification

- 11 API tests (`tests/test_api.py`), including the access token, validation errors, batch runs, reset, path-traversal safety and no-key mode.
- `scripts/ui_smoke.py` drives the real dashboard in headless Chromium at **1440×900 and 390×844**. It covers batch processing of all 40 messages, emergency detail, form validation, processing a new message, and every page. It also checks for no console errors and no horizontal scrolling. 31 of 31 checks passed. Screenshots are in `docs/screenshots/`.
- The production Docker image was built and run locally on port 10000 with an access token. Checked: health, dashboard, deep links, token refusal and acceptance, a live Groq call from inside the container, no `.env` in the image, and running as a non-root user.
- **Not verified:** an actual deploy on Render and Vercel, which needs the user's accounts.

## Trade-offs accepted

- Free Render services sleep after 15 minutes and lose in-memory state. Acceptable, because the brief only needs state to last for a run.
- One server process handles one agent task at a time. Concurrent users wait or get a "busy" message.
- Polling adds a little traffic during batch runs.
