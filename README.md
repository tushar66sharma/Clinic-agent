# Edvak_forge

**An AI front-desk agent for an outpatient clinic.** It reads patient messages arriving by SMS, portal and email. It works out what each sender needs and acts through the clinic's systems, using an MCP tool server. It escalates to a human whenever it should, and drafts a reply for staff to review. An evaluation harness measures how well it does, including every failure.

Built for the Edvak Forge take-home project. The clinic (Maplewood Family Clinic) and all patients are **fictional**. No real patient data is used anywhere.

![Inbox with an emergency message open](docs/screenshots/desktop-emergency-detail.png)

---

## Contents

1. [The problem](#the-problem)
2. [What it does](#what-it-does)
3. [Results](#results)
4. [How it works](#how-it-works)
5. [Architecture and why](#architecture-and-why)
6. [What was reused and what was built](#what-was-reused-and-what-was-built)
7. [Technology stack](#technology-stack)
8. [Repository structure](#repository-structure)
9. [Setup, step by step](#setup-step-by-step)
10. [Running it](#running-it)
11. [Testing and evaluation](#testing-and-evaluation)
12. [Deployment](#deployment)
13. [Security](#security)
14. [Troubleshooting](#troubleshooting)
15. [Limitations, next week, and before real patient data](#limitations-next-week-and-before-real-patient-data)
16. [Documentation](#documentation)

---

## The problem

The clinic receives dozens of messages a day: refill requests, appointment changes, billing questions, records requests and, occasionally, a real emergency. Staff read and act on each one by hand. It's slow, and **an urgent message can sit unnoticed for hours**.

The goal is an agent that works the inbox safely. It must never miss an emergency or answer one automatically, never break clinic policy, and never disclose patient information to the wrong person.

## What it does

- **Escalates emergencies at once.** It escalates chest pain, breathing trouble, stroke signs, head injury with confusion, very low blood sugar, bleeding on blood thinners, and suicidal thoughts. A code-level safety guard catches these before any AI call, and the AI is a second detector. The reply only tells the person to call 911 and that the clinic has been alerted.
- **Handles refills by policy.** It prepares eligible refills for provider approval and never approves them itself. Controlled substances and zero-refill prescriptions go to the provider. Patients not seen in 12 months are offered a visit. Too-early requests are told the earliest date.
- **Books, reschedules and cancels.** It respects opening hours, lunch, holidays, provider leave, visit lengths and existing bookings. It offers alternatives when the request can't be met.
- **Verifies identity before sharing anything.** The sender must write from the phone or email on file, or give a name plus a matching date of birth. Authorised caregivers are supported. Third parties are politely declined.
- **Resists manipulation.** "Ignore your instructions" messages are flagged, then handled under normal policy.
- **Routes to the right human queue.** The queues are urgent clinician, routine clinician, provider refills, front desk and billing.
- **Replies in the sender's language**, for example Spanish. Replies are checked so they never drop or invent a date or time.
- **Comes with a web dashboard.** You can process the inbox, inspect every decision and tool call, try new messages, and see the staff queues, schedule and evaluation.

## Results

Scored by the evaluation harness. Full reports are in [reports/](reports/README.md).

| Metric | 40 sample messages | 14 unseen messages |
|---|---|---|
| Fully correct (urgency, actions, patient, no violations) | 36 / 40 | 13 / 14 |
| **Emergencies escalated** | **5 / 5** | **3 / 3** |
| False emergency alarms | 0 | 0 |
| Urgency accuracy | 100% | 100% |
| Action exact match | 90.0% | 92.9% |
| Action precision / recall / F1 | 91.7% / 93.6% / 92.6% | — |
| Patient identified correctly | 100% | 100% |
| Bookings on the requested provider, day and time of day | 7 / 7 | — |
| Replies in the sender's language | 100% | 100% |
| **Forbidden actions (`must_not`)** | **0** | **0** |
| Safety-rule issues on any message | 0 | 0 |

The **unseen** messages were written after the agent was built, with expected answers fixed before the first run. The first, blind run also scored 13/14 with 3/3 emergencies.

**Cost and speed.** A full 40-message run makes about 70 AI requests and uses about 63,000–72,000 tokens. It costs **$0 on Groq's free tier**, or about **$0.014 at Groq's paid rates**. It takes about **8 minutes** on the free tier, because the client waits to stay under 8,000 tokens per minute. Reruns reuse cached answers and take seconds.

**What it gets wrong.**

| Message | What happened | Why it is kept |
|---|---|---|
| M004 | Also routes to the provider | The refill policy says to offer an appointment **and** route to the provider; the label omits the routing |
| M006 | Treats "I don't see the point of anything" as an emergency | The label accepts emergency urgency but expected a refill plus a same-day clinician; over-escalation is the safe direction |
| M019 | Adds a clinician review for post-surgery pain | Defensible, not expected |
| M022 | Asks which of two appointments to cancel instead of cancelling | Hannah Lee has two appointments that day; the agent does not guess |
| X014 (unseen) | "When is my next appointment?" goes to the front desk | No handler for that request yet; it fails safe |

Two real bugs were found by the evaluation and fixed. A booking for "next week, Tuesday" landed on this week's Tuesday. A reply invented a reopening day. See [docs/testing.md](docs/testing.md).

## How it works

```mermaid
flowchart LR
    M[Message] --> G{Safety guard:<br/>emergency red flags?}
    G -- yes --> E[Escalate to clinician_urgent<br/>fixed reply: call 911]
    G -- no --> A[AI reads the message<br/>→ structured analysis]
    A -- AI unavailable --> H[Hand to a human]
    A -- AI says emergency --> E
    A --> X[Code acts through MCP tools:<br/>verify · refill · book · route]
    X --> R[AI writes reply from facts]
    R --> C{Reply matches<br/>the facts?}
    C -- yes --> D[Draft for staff]
    C -- no --> T[Plain template] --> D
```

1. **Guard (code).** Pattern checks for emergencies. On a match, the agent escalates immediately, without waiting for the AI.
2. **Analyse (AI, 1 call).** The model turns free text into a structured description: intents, urgency, who the message is about, medications, the appointment window wanted, and any suspicious instruction. It takes no actions.
3. **Act (code, via MCP tools).** Fixed, safe steps: identify the patient, then verify the sender, then check refills, book, reschedule, cancel, answer or route. **Every clinic rule is enforced inside the tools**, so a model mistake can't prepare an ineligible refill, book a holiday, or read an unverified patient's data.
4. **Reply (AI, 1 call).** Written only from the facts produced in step 3, then checked by code.

More detail, with a diagram per workflow, is in [docs/workflows.md](docs/workflows.md).

## Architecture and why

```mermaid
flowchart LR
    Browser[Dashboard<br/>React] -->|/api| API[FastAPI]
    CLI[Batch runner CLI] --> Agent
    API --> Agent[Agent<br/>guard · analyse · act · reply]
    Agent -->|MCP| Tools[MCP tool server<br/>16 tools]
    Tools --> Rules[Clinic rules in code<br/>identity · refills · scheduling]
    Rules --> Data[(Clinic data<br/>in memory)]
    Agent -->|HTTPS| LLM[(Free AI provider<br/>Groq by default)]
    Eval[Evaluation harness] --> Runs[(Run outputs)]
    Agent --> Runs
```

The key decisions, each with a full record in [docs/decisions/](docs/decisions/):

- **Policy and safety live in code, not in the prompt** ([ADR 0004](docs/decisions/0004-safety-and-policy-in-code.md)). Rules with one right answer, like refill eligibility, booking rules and verification, are plain tested code. The model handles language. Two independent emergency detectors (guard and model) back each other up.
- **Planner-executor instead of a free-form tool-calling loop** ([ADR 0006](docs/decisions/0006-planner-executor-agent.md)). The free Groq tier allows 8,000 tokens per minute. A loop that resends 16 tool schemas every turn would need about 2 hours per run. This design needs about 3,000 tokens per message, and it's repeatable and auditable.
- **Privacy enforced by the tool server** ([ADR 0005](docs/decisions/0005-verification-token.md)). Health and appointment tools require a verification token that only `verify_sender` issues, after the clinic's rule passes.
- **Any free AI provider, switched by configuration** ([ADR 0002](docs/decisions/0002-llm-provider.md)). Groq, Cerebras, OpenRouter, Mistral or local Ollama all work through one adapter. Gemini is excluded by project rule.
- **In-memory data, fresh each run** ([ADR 0003](docs/decisions/0003-data-store.md)). This gives repeatable evaluation with nothing to install. The brief only needs changes to persist for a run.
- **One Docker image for API and dashboard** ([ADR 0008](docs/decisions/0008-dashboard-and-deployment.md)). One URL, free hosting on Render.

Details: [docs/architecture.md](docs/architecture.md) · [docs/system-design.md](docs/system-design.md).

## What was reused and what was built

**Reused:**
- The official **MCP Python SDK** (server and client).
- **FastAPI**, **Pydantic**, the **`openai` client** (pointed at Groq's OpenAI-compatible endpoint) and **python-dotenv**.
- **React**, **Vite**, **Tailwind CSS**, **React Router** and **lucide** icons.
- **pytest**, **ruff** and **Playwright**.
- The AI models: **gpt-oss-120b** and **gpt-oss-20b**, hosted by Groq.

**Built for this project:**
- The clinic rule modules and their tests.
- The 16 MCP tools, plus the verification-token privacy gate.
- The emergency guard.
- The planner-executor agent, with its reply faithfulness check.
- The provider-independent AI layer: retries, throttling, caching and JSON repair.
- The evaluation harness, with must-not checks, safety invariants and booking-detail checks.
- 14 unseen test messages with labels.
- The web API and dashboard.
- The Docker and Render setup.
- All the documentation.

No agent framework (LangChain and similar) was used. The pipeline is small, and a framework would hide the behaviour that matters most here: which tools are called, in what order, and why.

## Technology stack

| Technology | Version | Why |
|---|---|---|
| Python | 3.12 (3.11+) | Official MCP SDK; quick to write and test |
| MCP Python SDK | 2.3 | The brief asks for an MCP tool server |
| Pydantic | 2 | Validates data files, AI output and the result format |
| FastAPI + Uvicorn | 0.14x | Typed API, automatic docs at `/api/docs` |
| openai (client library) | 3.x | One adapter for every OpenAI-compatible provider |
| Groq `openai/gpt-oss-120b` + `openai/gpt-oss-20b` | — | Free tier, fast, strict JSON-schema output |
| React + TypeScript | 19 / 5.9 | Mainstream, typed UI code |
| Vite + Tailwind CSS | 8 / 4 | Fast builds, consistent design tokens |
| Docker, Render, Vercel | — | Free hosting with a reproducible image |

## Repository structure

```
Edvak_forge/
├── README.md                 ← you are here
├── CLAUDE.md                 project rules for the AI coding assistant
├── .env.example              configuration template (copy to .env)
├── pyproject.toml            Python package and dependencies
├── Dockerfile, render.yaml   production image and Render Blueprint
├── data/
│   ├── clinic.json, patients.json, medications.json, appointments.json   clinic data (synthetic)
│   ├── messages_sample.json, labels_sample.json                          the brief's 40 messages + answers
│   ├── messages_extra.json, labels_extra.json                            14 unseen test messages + answers
│   └── label_details_sample.json                                         booking details for the evaluation
├── src/edvak_forge/
│   ├── clinic/               clinic rules (identity, refills, scheduling) and the service layer
│   ├── mcp_server.py         the MCP tool server
│   ├── llm/                  provider-independent AI layer
│   ├── agent/                guard, prompts, executor (the agent), batch runner
│   ├── evaluation/           evaluation harness
│   └── api/                  web API for the dashboard
├── frontend/                 React dashboard (src/pages, src/components, design tokens in src/index.css)
├── tests/                    164 automated tests (no API key needed)
├── scripts/ui_smoke.py       browser test of the dashboard at desktop and mobile sizes
├── reports/                  published evaluation results
└── docs/                     all design documentation
```

## Setup, step by step

### Prerequisites

| Software | Version | Check with |
|---|---|---|
| Python | 3.11 or newer (developed on 3.12) | `python --version` |
| Node.js | 22 LTS (for the dashboard) | `node --version` |
| Git | any recent | `git --version` |
| Docker | optional, only to test the production image | `docker --version` |

Commands below are for **Windows PowerShell**. On macOS/Linux, replace `.venv\Scripts\python` with `.venv/bin/python`.

### 1. Get the code

```bash
git clone <your-repo-url> Edvak_forge
cd Edvak_forge
```

### 2. Install the Python part

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

The first line creates an isolated environment for this project's packages. The second installs the project with its test tools.

### 3. Check the installation

```bash
.venv\Scripts\python -m pytest -q
```

*Expected:* `164 passed`. The tests don't need an API key or internet access.

### 4. Get a free AI key and configure it

1. Sign up at https://console.groq.com (free, no card), open **API Keys**, and create one.
2. Copy the configuration template: `copy .env.example .env` (macOS/Linux: `cp .env.example .env`).
3. Open `.env` and paste the key after `GROQ_API_KEY=`.

`.env` is ignored by Git, so your key is never committed. Other free providers and how to switch are in [docs/ai-integration.md](docs/ai-integration.md).

### Environment variables

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `LLM_PROVIDER` | no | `groq` | `groq`, `cerebras`, `openrouter`, `mistral` or `ollama` |
| `GROQ_API_KEY` (or `<PROVIDER>_API_KEY`) | yes, for AI | — | Key for the chosen provider |
| `LLM_MODEL`, `LLM_REPLY_MODEL` | no | provider defaults | Override the analysis and reply models |
| `LLM_BASE_URL` | no | provider default | Override the endpoint |
| `LLM_TIMEOUT_SECONDS` | no | `60` | Give up on one AI request after this long |
| `LLM_MAX_RETRIES` | no | `4` | Retries on rate limits, timeouts and server errors |
| `LLM_MAX_REQUESTS_PER_MINUTE` | no | provider default | Client-side request throttle |
| `LLM_CACHE` | no | `1` | Reuse saved AI answers for identical requests (`0` = always call) |
| `CLINIC_TODAY` | no | `2026-11-09` | The clinic's "today" (fixed by the brief) |
| `DEMO_ACCESS_TOKEN` | no | — | If set, the web API requires it for actions that spend AI quota |
| `ALLOWED_ORIGINS` | no | `http://localhost:5173` | Websites allowed to call the API (only for split hosting) |
| `PORT`, `HOST` | no | `8000`, `0.0.0.0` | Where the web API listens |
| `EDVAK_HOME` | no | repo folder | Project folder, if the package is installed elsewhere |

There is no database, so there are no migrations. Clinic data loads from `data/` at start-up and resets on each run.

### 5. Install the dashboard (optional)

```bash
cd frontend
npm install
npm run build
cd ..
```

## Running it

**Process the 40 sample messages from the command line:**

```bash
.venv\Scripts\python -m edvak_forge.agent.runner
```

This takes about 8 minutes on the free tier, and the first run is the slowest. Results go to `runs/latest/`:
- `results.json` has one result per message in the brief's format.
- `traces.json` records every decision and tool call.
- `summary.json` has the time and token usage.

```bash
# A few messages, or your own file of new messages (same JSON format as data/messages_sample.json)
.venv\Scripts\python -m edvak_forge.agent.runner --only M003,M018,M029
.venv\Scripts\python -m edvak_forge.agent.runner --messages my_messages.json
# Without any AI (emergency guard + hand-off to humans only)
.venv\Scripts\python -m edvak_forge.agent.runner --no-llm
```

**Run the web dashboard:**

```bash
.venv\Scripts\python -m edvak_forge.api
```

Open http://localhost:8000. The API serves the built dashboard. Interactive API docs are at http://localhost:8000/api/docs.

To work on the dashboard with live reload, run the API as above, and in a second terminal:

```bash
cd frontend
npm run dev
```

Then open http://localhost:5173.

| Dashboard page | What you can do |
|---|---|
| Inbox | Process the sample or unseen set (all, or one message at a time); open any message to see the outcome, reply draft, reasoning and every tool call |
| New message | Type any message, or pick an example, and process it live |
| Staff queues | Tickets per queue, refill requests awaiting approval, flagged messages, appointment changes; reset the clinic data |
| Schedule | Each provider's day; bookings made by the agent are highlighted |
| Evaluation | Scores, missed emergencies, violations and per-message differences from the published reports |
| System | Server and AI status, access token, clinic configuration |

**Run the MCP tool server on its own**, for MCP Inspector, Claude Desktop or another MCP client:

```bash
.venv\Scripts\python -m edvak_forge.mcp_server
```

## Testing and evaluation

```bash
.venv\Scripts\python -m pytest -q                       # 164 tests, no API key needed
.venv\Scripts\python -m ruff check src tests            # lint
cd frontend && npm run build                            # type-check + build the dashboard
.venv\Scripts\python -m edvak_forge.evaluation --agent  # run the agent, then score it
.venv\Scripts\python -m edvak_forge.evaluation --agent --messages data/messages_extra.json --labels data/labels_extra.json
```

Browser test of the dashboard. The API must be running and the dashboard built first:

```bash
.venv\Scripts\python -m pip install -e ".[ui-test]"
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python scripts/ui_smoke.py
```

What each test covers, the metric definitions and the bugs found are in [docs/testing.md](docs/testing.md).

## Deployment

The whole app deploys **for free as one Render web service** from the included `Dockerfile` and `render.yaml`. Alternatively, the API can go on Render and the dashboard on Vercel.

The beginner guide, with every click, expected results, limits, logs, rollback and troubleshooting, is in **[docs/deployment.md](docs/deployment.md)**.

Free-tier facts to know:
- **Render's free service sleeps after 15 minutes** without traffic and takes about a minute to wake.
- **In-memory state resets** when it sleeps.
- **Vercel Hobby is for non-commercial use only.**

To test the production image locally:

```bash
docker build -t edvak-forge .
docker run --rm -p 10000:10000 --env-file .env edvak-forge   # open http://localhost:10000
```

## Security

- **Keys stay out of the code.** API keys are only in `.env` locally, or in the hosting platform's secret settings. They are never in Git, never in the Docker image, and never sent to the browser.
- **Privacy is enforced by the tools.** Unverified senders can't trigger any read of health or appointment data.
- **Emergencies are protected.** Replies to them are a fixed template, and no reply may contain clinical advice. The evaluation checks this on every message.
- **Public deployments can be protected.** Set `DEMO_ACCESS_TOKEN`, so strangers can look but can't spend your AI quota or reset data.

Everything, including what must change before real patient data, is in [docs/security.md](docs/security.md).

## Troubleshooting

| Problem | Fix |
|---|---|
| `GROQ_API_KEY is not set` | Create `.env` from `.env.example` and add the key |
| Runs pause for about a minute at a time | Normal: the free tier allows 8,000 tokens per minute |
| Messages routed to `front_desk` with path `fallback_no_model` | The AI failed after retries. See `llm_error` in `runs/latest/traces.json`; wait, or switch provider |
| `http://localhost:8000` shows a JSON 404 | Build the dashboard: `cd frontend && npm install && npm run build` |
| "This action needs the access token" | Enter it on the dashboard's System page |
| Spanish text garbled in the Windows console | Set `PYTHONIOENCODING=utf-8` |

More: [docs/troubleshooting.md](docs/troubleshooting.md).

## Limitations, next week, and before real patient data

**Known limitations**
- **Unhandled requests go to the front desk.** Requests with no handler, such as "when is my next appointment?", are handed to staff rather than answered.
- **The guard is pattern-based.** The emergency guard can miss new phrasings. The AI is the second detector; both missed nothing in 54 messages, but that is a small sample.
- **Some checks are heuristics.** The reply-language and clinical-advice checks are pattern-based, so replies were also read by hand.
- **One shared state.** Clinic state is in memory and shared by everyone using one server, and one agent task runs at a time.
- **Free-tier limits.** Full runs are slow, and the daily caps are unpublished.
- **Not measured: run-to-run variation.** Results come from single runs at temperature 0. Variation between runs wasn't measured, to save quota.

**With another week, I would:**
1. **Expand the test set.** Build a few hundred varied messages, especially emergency phrasings in several languages, written with clinicians, and run several times to measure variance.
2. **Judge replies with an AI.** Add an LLM-as-judge pass for reply quality and policy compliance, validated against human ratings.
3. **Add missing handlers.** Cover "what's my next appointment", prescription status, and multi-request messages that need clarification.
4. **Add an optional free-form tool-calling mode** for unusual requests on providers with higher limits, and compare it with the current pipeline.
5. **Route by confidence.** Low-confidence analyses would go to a human automatically.
6. **Persist state.** Use SQLite or Postgres for queues and bookings, with an audit trail.

**Before this touched real patient data**
- Real staff authentication and role-based access.
- Encrypted storage, and a durable, tamper-evident audit log.
- An AI provider under a business associate agreement (HIPAA or equivalent), with zero data retention. Free tiers are not appropriate.
- Stronger identity checks, such as one-time codes.
- Clinical safety validation of escalation with clinicians.
- Human approval of every outgoing reply.
- Monitoring of missed emergencies and of response times.
- A privacy and security review.

Details: [docs/security.md](docs/security.md#known-gaps-to-address-before-real-patient-data).

## Documentation

| Document | What it covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Components and technology choices |
| [docs/system-design.md](docs/system-design.md) | Tool catalogue, layers, where each rule lives |
| [docs/workflows.md](docs/workflows.md) | Every kind of message, with diagrams |
| [docs/ai-integration.md](docs/ai-integration.md) | Free AI providers, keys, limits, switching |
| [docs/error-handling.md](docs/error-handling.md) | Failures, retries, fallbacks, diagnostics |
| [docs/security.md](docs/security.md) | Privacy, secrets, API protections, gaps |
| [docs/testing.md](docs/testing.md) | Tests, evaluation metrics, results, cost |
| [docs/deployment.md](docs/deployment.md) | Free deployment, step by step |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems and fixes |
| [docs/decisions/](docs/decisions/) | Eight decision records with alternatives and trade-offs |
| [docs/progress-log.md](docs/progress-log.md) | Dated log of every step |
| [reports/](reports/README.md) | Published evaluation results |

<details>
<summary>More screenshots</summary>

| Desktop | Mobile |
|---|---|
| ![Evaluation](docs/screenshots/desktop-evaluation.png) | ![Inbox](docs/screenshots/mobile-inbox.png) |
| ![New message](docs/screenshots/desktop-new-message.png) | ![Schedule](docs/screenshots/mobile-schedule.png) |
| ![Staff queues](docs/screenshots/desktop-queues.png) | ![Emergency detail](docs/screenshots/mobile-emergency-detail.png) |

</details>
