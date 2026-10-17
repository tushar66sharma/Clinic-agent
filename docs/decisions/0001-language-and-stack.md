# ADR 0001: Language and technology stack

- **Status:** Accepted
- **Date:** 2026-10-18

## Context

The take-home brief asks for three things: an MCP tool server over the clinic data, an agent that uses those tools, and an evaluation harness. The project rules (CLAUDE.md) also ask for a web frontend and free-tier deployment. Any language is allowed. The timebox is about 6–8 hours, so the stack must be familiar, well-documented, and quick to test.

## Decision

| Part | Choice |
|---|---|
| MCP server, agent, evaluation harness, HTTP API | **Python 3.12** |
| MCP library | Official **MCP Python SDK** (`mcp`, FastMCP API) |
| HTTP API for the frontend | **FastAPI** |
| Data validation and output schema | **Pydantic v2** |
| LLM client | **`openai` Python SDK** pointed at OpenAI-compatible endpoints (see ADR 0002) |
| Tests | **pytest** |
| Frontend | **React + Vite + TypeScript + Tailwind CSS** |

## Why

- The official MCP Python SDK is mature and maintained by the protocol authors, so the tool server stays small.
- Pydantic gives one source of truth for the output format. The agent's result is validated against the exact schema in the brief before it is saved.
- The evaluation harness is plain data comparison, which is short and readable in Python.
- React with Vite is a standard, well-supported choice for a polished dashboard, and deploys free on Vercel.

## Alternatives considered

- **All TypeScript (Node MCP SDK + Next.js).** One language end to end and simpler Vercel hosting. Rejected because Python is faster for the agent and evaluation work, and the user did not request TypeScript.
- **An agent framework (LangChain, LlamaIndex, CrewAI).** Rejected. The agent loop is small, and a framework would hide exactly the behaviour reviewers want to inspect: which tools are called and why. A hand-written loop is easier to explain and debug.

## Trade-offs accepted

- Two languages in one repo (Python backend, TypeScript frontend), so two toolchains to install.
- The backend and frontend deploy to two different free platforms (see the deployment guide once written).
