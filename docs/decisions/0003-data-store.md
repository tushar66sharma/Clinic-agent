# ADR 0003: Serve clinic data from JSON files in memory, not MongoDB

- **Status:** Accepted
- **Date:** 2026-10-18

## Context

The brief allows either MongoDB or serving the JSON files directly. Bookings, reschedules and cancellations only need to last for one run. The dataset is tiny: 25 patients, 21 medications, 170 appointments.

## Decision

Load the six JSON files from `data/` into an in-memory store at startup. Every run, and every evaluation, starts from a fresh copy, so results are repeatable. All reads and writes go through a small repository class, so a database can replace it later without touching the tools.

## Why

- No database to install, run or host, which keeps local setup to a few commands and fits free-tier hosting.
- Repeatable evaluation: each run starts from the same schedule, so a booking in one message cannot silently change the result of another run.
- The repository boundary keeps the option of MongoDB open.

## Alternatives considered

- **MongoDB (local or Atlas free tier).** Closer to production, but adds setup, a hosted dependency, and state that must be reset between runs. No requirement needs it.
- **SQLite.** Real queries and transactions, but more code than the data size justifies.

## Trade-offs accepted

- Changes are lost when the process restarts. This matches the brief.
- In the web app, one process holds one shared schedule. The API will offer a reset action. Multi-user persistence is out of scope and listed as a known limitation.
- Within one run, messages are processed in order, so an earlier booking can affect later slot searches. This is intended, like a real inbox.
