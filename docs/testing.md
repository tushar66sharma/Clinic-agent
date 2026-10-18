# Testing

> **Status:** Complete. 164 automated tests, the evaluation harness, a browser test of the dashboard, and a verified production image. Published results are in [`reports/`](../reports/README.md).

## Run the tests

From the project folder, with the virtual environment set up (see README):

```bash
.venv/Scripts/python -m pytest -q        # Windows
.venv/bin/python -m pytest -q            # macOS / Linux
```

Lint:

```bash
.venv/Scripts/python -m ruff check src tests
```

## What is tested

| File | Covers |
|---|---|
| `tests/test_identity.py` | Name and phone normalisation, patient search, verification including caregivers, the wrong-DOB case (M011), the third-party case (M027), unknown senders (M007, M038) |
| `tests/test_refills.py` | Every refill message in the labels (M001, M004, M005, M006, M009, M012, M013, M018, M019, M020, M021, M025, M026, M036), the 7-day boundary, brand and Spanish names, leap-day date maths |
| `tests/test_scheduling.py` | Each booking rule on its own, plus every scheduling trap: taken slot (M029), provider leave (M028), holidays (M023, M034), Friday afternoon (M002), Tuesday morning (M010), same-day sick visit (M015), 40-minute physical (M024) |
| `tests/test_service.py` | Verification gate on every health tool, refusal to prepare ineligible refills, duplicate protection, safe rescheduling, idempotent cancel, clock-aware slots, error handling |
| `tests/test_mcp_server.py` | The real MCP protocol through an in-process client: tool list, a full refill flow, reset, refusal without verification, schema rejection of bad enum values |
| `tests/test_guard.py` | Emergency guard: the sample emergencies, **10 emergency phrasings it was not tuned on** (including Spanish), idioms and negations that must not trigger, urgent-level signals, the safe reply template |
| `tests/test_llm.py` | AI layer without network: Gemini refused, unknown provider, missing key, provider switch by config only, retry on 429, no retry on bad key, JSON repair retry, strict-schema conversion, throttle |
| `tests/test_api.py` | Web API: health, no-key mode, inbox, processing a new message, one error format for validation, input size limits, access token, batch run and reset, schedule (leave and holidays), report listing and path-traversal safety |
| `tests/test_evaluation.py` | The harness catches what it should: missed emergency, false alarm, forbidden action, refill-only, clinical advice, approval claims, PHI leak, double booking, booking on leave, ineligible refill, wrong booking date, unknown codes |
| `tests/test_agent.py` | Whole agent over a real in-process MCP connection with a scripted fake model: emergencies skip the model, model failure goes to a human, urgency floor, third-party decline, wrong-DOB verification, prompt injection, controlled substances, taken slot, ambiguous cancel, spam, billing routing, reply faithfulness and template fallback, valid output for all 40 messages |

The tests use the real files in `data/`. Each test gets a fresh copy, so tests cannot affect each other. No test calls a real AI provider; `tests/fakes.py` provides a scripted stand-in.

## Dashboard and deployment checks

| Check | How | Result (2026-10-18) |
|---|---|---|
| Dashboard type-check and build | `cd frontend && npm run build` | Passes. About 100 KB gzipped JavaScript |
| Main user journeys at **1440×900** and **390×844** | `python scripts/ui_smoke.py`: process all 40 messages, open an emergency, form validation, process a new message, every page, no console errors, no horizontal scrolling | 31 / 31 checks passed. Screenshots in `docs/screenshots/` |
| Production image | `docker build` then `docker run -p 10000:10000` with an access token | Health ok; dashboard and deep links served; actions refused without the token and accepted with it; live Groq call from inside the container; no `.env` in the image; runs as non-root; 278 MB |
| Real Render / Vercel deploy | Needs the user's accounts | **Not verified** |

## Live runs against Groq

| Run | Messages | Time | Model requests | Tokens | Fully matching labels | Emergencies escalated | Forbidden actions |
|---|---|---|---|---|---|---|---|
| `full1` (2026-10-18) | 40 | 491 s | 55 (+14 cached) | 72,471 | 35 / 40 | 6 / 6 | 0 |
| `full2` after billing fix | 40 | 6 s (cached) | 1 (+68 cached) | 336 | 36 / 40 | 6 / 6 | 0 |

These early counts came from a quick script. The figures below come from the evaluation harness.

## Evaluation harness

The harness scores a saved agent run against labels. Design and metric definitions are in [ADR 0007](decisions/0007-evaluation-design.md).

```bash
# Run the agent on the 40 sample messages, then score them
.venv\Scripts\python -m edvak_forge.evaluation --agent
# Score an existing run
.venv\Scripts\python -m edvak_forge.evaluation --run runs/latest
# The 14 unseen messages
.venv\Scripts\python -m edvak_forge.evaluation --agent --messages data/messages_extra.json --labels data/labels_extra.json
# Fail with exit code 1 on any missed emergency or safety problem (for CI)
.venv\Scripts\python -m edvak_forge.evaluation --strict
# Copy outputs into reports/<name>/ for the submission
.venv\Scripts\python -m edvak_forge.evaluation --run runs/latest --publish sample-40
```

Each run directory gets `eval.json` (all numbers) and `report.md` (readable report).

### Final results (2026-10-18, Groq `gpt-oss-120b` + `gpt-oss-20b`)

| Metric | 40 sample messages | 14 unseen messages |
|---|---|---|
| Fully correct | 36 / 40 | 13 / 14 |
| **Emergency recall** | **100% (5/5)** | **100% (3/3)** |
| Emergency false alarms | 0 | 0 |
| Urgency accuracy | 100% | 100% |
| Action exact match | 90.0% | 92.9% |
| Action precision / recall / F1 | 91.7% / 93.6% / 92.6% | see report |
| Patient identification | 100% | 100% |
| Bookings matching the request (provider, dates, time of day) | 7 / 7 | not labelled |
| Reply in the sender's language | 100% | 100% |
| **must_not violations** | **0** | **0** |
| Safety invariant issues | 0 | 0 |

### What the agent gets wrong (40 sample messages)

| Message | Difference | Why it is kept |
|---|---|---|
| M004 | Extra `route_to_provider` | The refill policy says to offer an appointment **and route to the provider**. The label omits the routing. |
| M006 | Escalated as emergency instead of refill + clinician | The model read "don't see the point of anything" as possible suicidal ideation. The label accepts emergency urgency. Over-escalation is the safe direction. |
| M019 | Extra `route_to_clinician` | The model asked a clinician to review ongoing post-surgery pain alongside the controlled-substance routing. Defensible, but not expected. |
| M022 | Asks which appointment instead of cancelling | Hannah Lee has two appointments that day and wrote "my appointment". The agent asks rather than guessing. |
| X014 (unseen) | Routed to front desk instead of answering | No handler for "when is my next appointment?". It fails safe. |

### Bugs the evaluation found

- **M010 booked the wrong week.** "Next week, ideally Tuesday" was booked on this week's Tuesday. The label-level score marked it correct. It was found by reading replies by hand. The prompt was fixed, and the harness now checks booking details, so this class of bug is caught automatically.
- **Invented reopening day.** One reply said the clinic reopens "the following day" after Thanksgiving, which is also a holiday. The code now supplies the true next open day.
- **The checks' own false positives.** "Once it is approved" was flagged as an approval claim, and a Spanish reply was misread as English. Both checks were fixed and tested.

### Cost

A full uncached run of the 40 sample messages uses about 70 model requests and 63,000–72,000 tokens, and takes about 8 minutes on the free tier.

| | |
|---|---|
| Cost on Groq's free tier | $0 |
| Cost at Groq's published paid rates ($0.15 / $0.60 per million tokens for gpt-oss-120b; $0.075 / $0.30 for gpt-oss-20b, checked 2026-10-18) | about **$0.014 per 40-message run** |

### Known limits of the evaluation

- The clinical-advice and reply-language checks are pattern heuristics. Replies were also read by hand for this submission.
- Booking constraints for the sample set were transcribed from the labels' trap text into `data/label_details_sample.json`.
- The unseen set has 14 messages, written by the developer, so it is a sanity check, not a benchmark.
- Results come from one run at temperature 0. Run-to-run variation on the free tier was not measured, because of quota.

## Last result

| Date | Result |
|---|---|
| 2026-10-18 | 78 passed, lint clean. MCP server also checked manually as a subprocess over stdio. |
| 2026-10-18 | 135 passed, lint clean. Full 40-message live run completed over the stdio MCP server. |
| 2026-10-18 | 153 passed, lint clean. Final evaluation runs published in `reports/`. |
| 2026-10-18 | 164 passed, lint clean, dashboard build passes, browser smoke 31/31, production image verified. |
