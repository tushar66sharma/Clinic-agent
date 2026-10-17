# ADR 0006: Planner-executor agent instead of a free-form tool-calling loop

- **Status:** Accepted
- **Date:** 2026-10-18

## Context

The usual way to build a tool-using agent is a loop: send the model the conversation plus every tool's schema, let it pick a tool, run it, append the result, and repeat until it answers.

We measured the Groq free plan on this account from its response headers: **1,000 requests per day and 8,000 tokens per minute per model**. Our 16 tool schemas plus policy instructions come to roughly 4–5K tokens, and they are resent on every turn. A typical message needs 4–6 turns. That is about 25K tokens per message, so the per-minute cap allows roughly one message every three minutes. A 40-message run would take about two hours.

Reliability matters as much as cost. In a free-form loop, the model decides the order of actions. It might skip verification, or book before checking the slot. It might also stop before routing to a human.

## Decision

Each message goes through a fixed pipeline:

1. **Guard (code).** A red-flag check for emergencies. On a match, the agent escalates at once: it identifies the patient, routes to `clinician_urgent`, and sends the fixed safe reply. **No model call is made.**
2. **Analyse (model, 1 call).** The model turns the free text into a structured `Analysis`: intents, urgency, who the message is about, medications, the requested appointment window, questions, and any suspicious instruction. It does not act.
3. **Act (code, through MCP tools).** Handlers for each intent call the MCP tools in a fixed, safe order: identify, then verify, then refill checks, booking, rescheduling, cancelling, routing and answering. Policy outcomes come from the tools themselves.
4. **Reply (model, 1 call).** The model writes the reply from a list of plain facts produced in step 3. Code checks the reply is faithful: every date and time from the facts must appear, and no others. If the check fails, the model gets one retry, then a template is used.

## Why

- **Cost.** About 3K tokens per message instead of about 25K. A full run takes about 10–15 minutes on the free tier instead of about 2 hours.
- **Safety.** Emergencies never wait on a rate-limited API and are never answered by a model. Verification always happens before any health data is touched.
- **Repeatability.** The same analysis always leads to the same actions, so evaluation results are stable and failures can be traced to either the analysis or the code.
- **Explainability.** Each result has a trace with the path taken, the model's analysis, the facts and every tool call.

## Alternatives considered

- **Free-form tool-calling loop (ReAct).** More flexible for unusual requests, but about 8 times the tokens, and the order of actions isn't guaranteed. It remains a good option with a provider that has higher limits. It could be added as a second mode behind the same tool server.
- **Rules only, no model.** Brittle on free text, other languages, and the unseen messages in the walkthrough.
- **One model call that analyses and writes the reply together.** Saves a call, but the model would write the reply before the tools ran, so it could promise a slot that turns out to be taken.

## Trade-offs accepted

- Requests that fit no handler are routed to the front desk instead of being creatively solved. That is the safe failure mode for a clinic.
- New kinds of requests need a new handler in code, not just a prompt change.
- The model's analysis can still be wrong, for example picking the wrong intent. The evaluation harness measures how often.
