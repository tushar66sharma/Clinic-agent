# Error handling and recovery

Principle: **no message is ever dropped, and failure always falls toward a human.** An emergency never depends on anything that can fail slowly, such as the AI provider.

## Failure table

| What fails | Detected by | Retried? | What happens | What the sender sees |
|---|---|---|---|---|
| AI provider rate limit (429) | `openai.RateLimitError` | Yes, up to `LLM_MAX_RETRIES`, honouring `Retry-After`, exponential backoff | If still failing: `LLMRateLimitError` → fallback path, routed to front desk (or clinician_urgent if the guard saw urgent signs) | "A member of our team will review your message" |
| Provider timeout | `APITimeoutError` | Yes | Same as above | Same |
| Provider down / network | `APIConnectionError`, 5xx | Yes | Same as above | Same |
| Bad API key or no model access | 401 / 403 / 404 | No | Run stops at startup with a clear message if the key is missing. Mid-run, messages fall back to humans | Same as above |
| Model output not valid JSON or wrong shape | Pydantic validation, or Groq `json_validate_failed` | One repair retry showing the model its error | Then `LLMResponseError` → fallback path | Same as above |
| Reply drops or invents a date/time | `unfaithful()` check | One retry with feedback | Then a plain template built from the facts | Template reply with correct facts |
| Reply model fails | `LLMError` | — | Template reply from facts | Template reply |
| Tool returns `ok: false` | Checked by each handler | Booking tries the next slot | Alternatives offered, or staff told via notes | An explanation and options |
| Tool input rejected by schema | MCP `is_error` | No | Recorded in the trace | Depends on handler; usually routed to a human |
| MCP transport broken | Exception in `ToolSession.call` | No | Recorded as `tool_transport_error`; handler continues | Usually a hand-off to staff |
| Unexpected bug while processing | `try/except` in the runner | No | Result forced to `urgent`, `route_to_front_desk`; full traceback logged | Generic "we'll get back to you" |
| Emergency while the AI is down | Guard runs before the model | — | Escalated normally; no model needed | The safe 911 template |

## Rate limits on the free tier

The client throttles itself before the provider has to refuse. It uses a sliding 60-second window per model for requests and tokens. Token counts are estimated before each call and corrected with the real usage afterwards. If Groq still returns 429, its `Retry-After` header is respected. During a full run you will see pauses of up to a minute. That is normal.

## Duplicates and inconsistent state

- `route_to_queue` creates at most one ticket per message per queue.
- `prepare_refill_request` creates at most one request per patient and medication per run.
- Cancelling an already cancelled appointment succeeds without changing anything.
- Rescheduling books the new slot before cancelling the old one, so the patient can't end up with no appointment.
- Each run starts from a fresh copy of the data (`admin_reset_state`), so reruns don't interfere.

## Diagnostics

| Where | What |
|---|---|
| Console log | One line per message: urgency, actions, seconds. HTTP status of each model call |
| `runs/<time>/traces.json` | Per message: path taken, guard matches, the model's analysis, facts, notes (verification result, rejected replies, assumptions) and every tool call with arguments and results. Verification tokens are masked |
| `runs/<time>/summary.json` | Duration, provider, models, token usage, count of each path (`emergency_fast_path`, `fallback_no_model` and so on) |
| `runs/<time>/run_log.json` | Every queue ticket, refill request, reply draft, flag and appointment change |

A non-zero `fallback_no_model` count in the summary means the model failed for some messages. Check the `llm_error` field in their traces.
