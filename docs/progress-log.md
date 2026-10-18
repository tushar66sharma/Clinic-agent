# Progress log

A dated record of each step: what was done, what was decided, and what is still open. Newest entries go at the bottom.

## 2026-10-18 — Step 1: decisions and scaffolding

**Done**
- Read the take-home brief, all six data files, all 40 messages and all 40 labels.
- Saved project rules and context in `CLAUDE.md`.
- Initialised the git repository on branch `main`. Nothing committed yet.
- Copied the six data files into `data/` so the repo is self-contained.
- Added `.gitignore` (blocks `.env`, caches, run outputs) and `.env.example`.
- Checked free LLM providers against official docs and recorded results.
- Wrote decision records 0001–0004 and the first version of `docs/ai-integration.md`.

**Decided**
- Python 3.12 backend with the official MCP SDK, React frontend (ADR 0001).
- Groq `gpt-oss-120b` as default provider behind a pluggable OpenAI-compatible adapter (ADR 0002).
- In-memory JSON data store, reset each run (ADR 0003).
- Clinic policy and emergency safety enforced in code (ADR 0004).

**Found**
- GitHub Models was retired on 2026-07-30, so it is not an option.
- Groq does not publish free-plan numbers publicly. Each user must check their account's limits page.
- A full run may exceed a free daily token cap. The agent design in step 3 must keep token use low.

**Open**
- Exact Groq free-plan limits for the user's account (needs the user's key).
- No code exists yet. Steps 2–5 follow.

## 2026-10-18 — Step 2: clinic tools (MCP server)

**Done**
- Python project set up: `pyproject.toml`, virtual environment in `.venv/`, package in `src/edvak_forge/`.
- Data models that validate every JSON file on load.
- Rule modules for identity, refills and scheduling, holding every clinic policy as plain code.
- `ClinicService` with a verification gate, consistent error format, run log and duplicate protection.
- MCP server with 16 agent tools and 3 harness-only admin tools.
- 78 tests, all passing. Lint clean. Server also checked as a real subprocess over stdio.
- Docs: `system-design.md`, `security.md`, `testing.md`, ADR 0005.

**Decided**
- Privacy enforced by a verification token issued by the tool server (ADR 0005).
- No bookings after 27 Nov 2026, the end of the known schedule.
- A simulated clock, set per message, hides same-day slots that have already passed.

**Found**
- The installed MCP SDK is version 2.3. `FastMCP` was renamed `MCPServer` in version 2, so the code uses the new name.
- **Hannah Lee (M022) has two appointments tomorrow**, at 11:00 with KIM and 15:00 with OKAFOR, but writes "my appointment". The label expects `cancel_appointment`. The agent design in step 3 must decide whether to cancel one, both, or ask.
- **`patient_id` in the labels is the patient the message is about, not only verified senders.** M011 (unverified sender) expects P002 and M027 (third party) expects P013. The brief says `null` if the sender is not verified. The agent will follow the labels, and this is recorded as a known ambiguity.

**Open**
- Agent (step 3) needs a Groq key in `.env`.

## 2026-10-18 — Step 3: the AI agent

**Done**
- Provider-independent AI layer in `src/edvak_forge/llm/`: one OpenAI-compatible adapter, provider registry (Groq, Cerebras, OpenRouter, Mistral, Ollama), timeouts, retries with backoff and `Retry-After`, per-model request and token throttle, strict JSON schema with one repair retry, normalised errors, on-disk response cache. Gemini is refused.
- Deterministic emergency guard with a fixed safe reply template (English, Spanish).
- Planner-executor agent: guard, then model analysis, then code acting through MCP tools, then model reply with a faithfulness check.
- Batch runner CLI writing results, traces, run log and summary to `runs/`.
- 57 new tests (135 total), including emergency phrasings the guard was not tuned on. Lint clean.
- Docs: ADR 0006, `architecture.md`, `workflows.md`, `error-handling.md`, rewritten `ai-integration.md`, README run instructions.

**Measured**
- Groq free plan on this account: 1,000 requests/day and 8,000 tokens/minute per model (from response headers).
- First full run over the real MCP subprocess: 40 messages in 491 s, 55 model requests, about 72K tokens, $0. 36 of 40 results fully match the labels after one bug fix. All 6 emergencies escalated, 5 of them by the guard without a model call. No forbidden action taken.

**Decided**
- Planner-executor instead of a free-form tool-calling loop, because of the 8K tokens/minute limit and for reliability (ADR 0006).
- Replies from `gpt-oss-20b`, analysis from `gpt-oss-120b`: separate per-model quotas.
- Ambiguous cancellation (Hannah Lee, two appointments) asks the patient instead of guessing.
- Not tuning prompts to the four remaining label mismatches. Each is a defensible judgement (see below), and tuning to 40 labels risks overfitting.

**Bugs found and fixed during this step**
- A tool argument called `name` clashed with the MCP wrapper's parameter. The crash safety net caught it and routed those messages to staff.
- The strict schema rejected a reschedule with no visit type. The visit type is now optional, and provider schema rejections get a repair retry.
- The throttle kept the reservation from failed requests and over-reserved output tokens, which caused needless 1-minute waits.
- The reply model dropped offered appointment times. Added the faithfulness check with retry and template fallback.
- Guard missed "pressure in his chest", found by an unseen-phrasing test. Pattern widened.
- A billing question was also sent to the front desk. Billing is now handled before general questions.
- An unverified husband was treated as a caregiver by the model. A code rule now makes unverified senders asking about someone else third parties.

**Remaining differences from the labels (run `runs/full2`)**
- M004: extra `route_to_provider`. The refill policy says "offer an appointment and route to the provider", so this follows the policy over the label.
- M006: the model judged "don't see the point of anything" as possible suicidal ideation, so it took the emergency path. The labels accept emergency urgency, but expect `route_to_clinician` and `prepare_refill_for_approval`. This is the safe direction, so it was kept.
- M019: urgency `urgent` instead of `routine` for post-surgery pain with an oxycodone request. Actions are correct.
- M022: asks which of two appointments to cancel instead of cancelling (design call).

**Open**
- Step 4: formal evaluation harness and report.
- Daily token cap on Groq's free plan is not shown in headers. A full uncached run uses about 60K tokens on the analysis model.

## 2026-10-18 — Step 4: evaluation harness

**Done**
- `src/edvak_forge/evaluation/` scores a saved run. It covers emergency recall and false alarms, urgency accuracy, action exact match and micro precision/recall/F1, a per-action table, patient identification, intents, reply language, booking details, every `must_not` code with evidence, and safety invariants on every message. It also reports cost at Groq's paid rates. Output is `eval.json` and `report.md`. `--strict` gives a CI-style exit code and `--publish` copies to `reports/`.
- `tests/test_evaluation.py` proves each check fires on deliberately bad input (153 tests in total).
- 14 unseen messages with labels written from policy before the first run (`data/messages_extra.json`, `data/labels_extra.json`).
- Booking constraints transcribed from the sample labels' trap text (`data/label_details_sample.json`).
- Published `reports/sample-40`, `reports/unseen-14` and `reports/unseen-14-blind`. ADR 0007.

**Results (final code)**
- Sample 40: 36/40 fully correct, emergency recall 5/5, urgency 100%, actions exact 90%, 0 must_not violations, 0 invariant issues, bookings 7/7 on the requested details.
- Unseen 14: 13/14, emergency recall 3/3, 0 violations. Blind run (before fixes) was also 13/14 with 3/3 emergencies.
- Cost: about $0.014 per 40-message run at paid rates, $0 on the free tier.

**Bugs found by the evaluation and fixed**
- M010 booked "next week, Tuesday" on this week's Tuesday, caused by my prompt rule "next such weekday". It was invisible to label-level scoring and found by reading replies. Prompt fixed, and the booking-detail check added.
- A reply invented "open again the following day" after Thanksgiving. Code now supplies the real next open day, and the reply rules forbid guessing.
- My own checks: "once it is approved" was a false approval claim, and the Spanish detector was too weak. Both fixed and tested.
- Guard gaps found blind: Spanish stroke signs and "ending my life" (the AI caught both). Patterns widened after the blind result was recorded.

**Decided**
- Report the blind unseen result separately from the post-fix result, so the generalisation claim stays honest.
- Not tuning towards the 4 remaining sample mismatches (M004, M006, M019, M022). Each is a defensible judgement and is documented.

**Open**
- Step 5: web dashboard and deployment.
- Reply quality beyond dates, times and advice patterns is checked by hand. An LLM-as-judge is future work.

## 2026-10-18 — Step 5: web dashboard and deployment

**Done**
- Web API (`src/edvak_forge/api/`): live shared clinic state over one in-process MCP connection, single-message processing, background batch runs with progress, staff queues, schedule, reports, reset. It also has an access token for actions, CORS settings, one JSON error format, bounded inputs, path-safe report and static serving, and no-key mode.
- AI calls moved to worker threads, so the server stays responsive while the agent waits on rate limits.
- Dashboard (`frontend/`): React 19 + Vite + TypeScript + Tailwind v4 with a token-based design system. Pages: Inbox, New message, Staff queues, Schedule, Evaluation, System. It has loading, empty, error, success-toast and confirmation states, plus keyboard focus rings, a skip link, labelled forms, a responsive sidebar or mobile drawer, and no horizontal scrolling.
- `Dockerfile` (multi-stage, non-root), `.dockerignore`, `render.yaml` Blueprint, `frontend/vercel.json`.
- Docs: `deployment.md` (beginner guide, two options), `troubleshooting.md`, ADR 0008, and full README rewrite. Updated architecture, security and testing docs.
- 11 API tests (164 in total) and the browser smoke test `scripts/ui_smoke.py` (31/31 at desktop and mobile).

**Verified**
- Production image built and run locally on port 10000. Health, dashboard, deep links, access-token refusal and acceptance, a live Groq call from the container, no `.env` in the image, non-root user.
- Render and Vercel free-tier limits checked in official docs (Render: 15-minute spin-down, about 1-minute wake, 750 hours/month, ephemeral filesystem. Vercel Hobby: free, non-commercial only).

**Decided**
- One Docker service on Render as the recommended deployment. Render API + Vercel dashboard as Option B (ADR 0008).
- Option B uses `pip install -e .`, so the app finds `data/` and `reports/` without guessing Render's checkout path. `EDVAK_HOME` was added for installs elsewhere (used in Docker).

**Not verified**
- An actual deploy on Render and Vercel, which needs the user's accounts and a GitHub repository.
- Option B end to end.

**Open**
- Nothing is committed to Git yet. The user decides when to commit and push.
