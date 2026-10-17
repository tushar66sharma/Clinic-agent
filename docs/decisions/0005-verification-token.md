# ADR 0005: Privacy enforced with a verification token issued by the tool server

- **Status:** Accepted
- **Date:** 2026-10-18

## Context

The privacy policy says health information and appointment details may only be disclosed to a verified patient or authorised caregiver. Two sample messages test this directly: a request for lab results from an unknown email with the wrong date of birth, and a husband asking about his wife's appointments. If the model alone decides whether to look up a patient's data, a prompt injection or a model mistake could leak it.

## Decision

- `verify_sender` applies the verification rule in code. When the sender passes, it returns a random `verification_token` bound to that one patient.
- Every tool that reads or changes health or appointment data requires that token: `get_patient_profile`, `get_medications`, `check_refill_eligibility`, `prepare_refill_request`, `list_appointments`, `book_appointment`, `reschedule_appointment`, `cancel_appointment`.
- A missing, made-up, or other-patient token returns `verification_required` and no data.
- Tokens live in server memory and disappear on reset. They are not secrets from the model; they prove that verification happened in this run, for this patient.

## Why

- The model cannot read data it was never given. Even a fully hijacked model can only call tools, and the tools refuse.
- It turns the privacy rule into a tested property of the system, not a sentence in a prompt.

## Alternatives considered

- **Re-verify inside every tool** by passing sender name and contact each time. Stateless, but makes every tool call longer and easier for the model to get wrong.
- **Per-message server session** set by the harness. Simpler calls, but couples the server to one message at a time and breaks if two messages are processed concurrently.
- **Prompt instructions only.** Rejected; not enforceable.

## Trade-offs accepted

- One extra tool call per message for verification.
- `find_patient` still returns names and ids for matching records without verification. That data stays inside the agent and is not shown to the sender. The agent is instructed never to confirm or deny that someone is a patient to an unverified sender.
