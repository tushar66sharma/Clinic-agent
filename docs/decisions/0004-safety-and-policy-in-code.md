# ADR 0004: Clinic policy and emergency safety enforced in code, not left to the model

- **Status:** Accepted
- **Date:** 2026-10-18

## Context

The brief says safety comes first: missing an emergency, or answering one automatically, matters more than anything else. Several sample messages are traps: a prompt injection, an idiom ("I'm dying to get in"), emergencies buried inside refill requests, controlled substances, provider leave, holidays, and third parties asking for someone else's information. Free-tier models are capable but not perfectly reliable.

## Decision

Split responsibilities:

- **The model** reads the message, picks intents, extracts details (which medication, which day), decides which tools to call, and writes the reply.
- **Deterministic code** owns every rule that has a right answer:
  - Refill eligibility (active list, controlled substance, seen within 12 months, refills remaining, 7-day window, earliest request date).
  - Booking rules (hours, lunch, :00/:20/:40 starts, holidays, provider leave, no overlaps, visit durations).
  - Identity verification (name + date of birth, or phone/email on file, including authorised caregivers).
  - Disclosure: tools refuse to return health or appointment details for an unverified sender.
- **A safety guard in code** runs around the model:
  - Before the model: a red-flag check for emergency signs (for example chest pain, trouble breathing, head injury with confusion, very low blood sugar, bleeding on blood thinners, self-harm language).
  - After the model: if either the guard or the model judges the message an emergency, the result is forced to `urgency: emergency`, `escalate_emergency`, routed to `clinician_urgent`, and the reply is replaced with the fixed safe template (call 911 or go to the nearest emergency department, the clinic has been alerted).
  - If the model call fails, the message is routed to a human queue instead of being dropped.

## Why

- Rules with one right answer should never depend on the model's mood. Code is testable and repeatable.
- Two independent emergency detectors (guard plus model) reduce the chance of a missed emergency. False alarms cost a staff member a minute. A missed emergency could cost a life.

## Trade-offs accepted

- The red-flag check is a keyword and pattern list, so it can over-trigger. Idioms like "dying to get in" must be excluded explicitly and tested.
- Some false-positive escalations are accepted on purpose. Emergency recall is valued above urgency accuracy.

## Alternatives considered

- **Let the model do everything from a long policy prompt.** Simpler, but a single model mistake could book on a holiday, prepare a controlled-substance refill, or miss an emergency.
- **A pure rules engine with no model.** Reliable on known phrasing, but brittle on free-text messages, Spanish, and unseen messages in the live walkthrough.
