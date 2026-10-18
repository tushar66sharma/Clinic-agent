# Security and privacy

> **Status:** Covers the whole system: tool server, agent, web API and dashboard.

## Patient privacy

**Rule (clinic.json):** never disclose health information or appointment details unless the sender is verified as the patient or an authorised caregiver. Verification is a name + date-of-birth match, or a message from the phone or email on file.

**How it is enforced:** in code, by the tool server, not by the prompt. See [ADR 0005](decisions/0005-verification-token.md).

| Situation | Result |
|---|---|
| Message from the patient's phone or email on file | Verified as the patient |
| Message from the caregiver's phone or email on file | Verified as caregiver |
| Patient name + correct DOB, from an unknown contact | Verified |
| Caregiver name + patient's correct DOB | Verified as caregiver (design call, policy is silent) |
| Stated DOB does not match the record | **Not verified**, even from a contact on file |
| Name matches but contact unknown and no DOB | Not verified |
| Someone not on file asking about a patient | Not verified |

Health and appointment tools refuse to run without a valid token for that exact patient.

## Data protection

- All data is synthetic. No real patient data is used anywhere.
- Data is held in memory only. Nothing is written to disk during a run.
- `find_patient` returns only ids, names and match reasons, never DOB, phone, medications or appointments.

## Secrets

- API keys live only in `.env` (git-ignored) or the hosting platform's secret settings.
- `.env.example` contains placeholders only.
- The tool server needs no secrets at all.

## Input validation

- Dates must be `YYYY-MM-DD`, times `HH:MM`. Invalid values return an error, never a crash.
- Queue, priority, visit type and provider are fixed lists in the MCP schema, so invalid values are rejected before the tool runs.
- Slot search results are capped at 20.

## Agent-level controls

- **Prompt injection.** The message body is wrapped as untrusted data and the model only describes it; code decides the actions. Suspicious instructions are flagged (`flag_suspicious_instruction`) and the genuine request is handled under normal policy. Even a fully hijacked model can only call tools, and the tools enforce policy.
- **Emergencies.** A deterministic guard escalates before any model call. Emergency replies are a fixed template, never model-written.
- **Replies** are written only from code-produced facts. When the sender is unverified, those facts contain no health data, so the model can't leak what it never saw. A faithfulness check rejects replies with dropped or invented dates and times.

## Web API and dashboard

| Control | Implementation |
|---|---|
| Secrets | Provider keys are read on the server only; the dashboard never receives them. The Docker image excludes `.env` (`.dockerignore`) and runs as a non-root user |
| Action protection | If `DEMO_ACCESS_TOKEN` is set, `POST /api/messages/process`, `POST /api/runs` and `POST /api/state/reset` require header `X-Access-Token`, compared in constant time. The dashboard keeps the token in `sessionStorage` for the current tab only |
| CORS | Only origins in `ALLOWED_ORIGINS` may call the API from a browser (default `http://localhost:5173`). Not needed for the single-service deployment |
| Input validation | Pydantic models bound field lengths (message body ≤ 2,000 characters, names ≤ 120), restrict channel values and date formats; errors return one JSON shape with per-field messages |
| Path safety | Report names must match an existing folder; static files are served only from inside `frontend/dist` |
| Errors | Unexpected exceptions return a generic message; details go to the server log only |
| Concurrency | One agent task at a time (lock); a second request gets `409 busy` instead of corrupting shared state |

The access token is a **demo safeguard against quota abuse, not user authentication**. Viewing endpoints, including synthetic patient names in the schedule and traces, are open.

## Known gaps (to address before real patient data)

- **Real authentication and authorisation** for staff (SSO, roles, per-user audit) instead of a shared demo token; viewing endpoints must be protected too.
- **Durable, tamper-evident audit log** of every message, tool call and reply, kept for the legally required period.
- **Data storage**: an encrypted database instead of in-memory JSON; backups; data retention and deletion rules.
- **AI provider contract**: a business associate agreement (HIPAA) or equivalent, zero-retention settings, and a provider in an approved region. Free tiers are not suitable for patient data.
- **Stronger identity verification**: contact-on-file alone can be spoofed (SMS spoofing, shared family phones); add one-time codes for sensitive requests.
- **Human review** of every reply before sending (the drafts are already marked for staff review) and monitoring of escalation response times.
- **Clinical safety validation** of the emergency guard with clinicians, on far more than 54 messages, plus continuous monitoring of missed emergencies.
- **No authentication on the MCP tool server.** It is designed to run inside the agent's process or as its subprocess, never exposed on a network.
- Verification tokens never expire within a run; they should be short-lived and bound to one message.
