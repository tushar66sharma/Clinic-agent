"""Render an evaluation as a Markdown report a reviewer can read top to bottom."""

from __future__ import annotations


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def render(ev: dict, *, title: str, run_dir: str) -> str:
    h, ops = ev["headline"], ev["operations"]
    pm = {m["id"]: m for m in ev["per_message"]}
    lines = [
        f"# {title}",
        "",
        f"Run: `{run_dir}` · provider `{ops['provider']}` · models `{ops['models']}`",
        "",
        "## Headline",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Messages fully correct (urgency, actions, patient, no violations) | {h['fully_correct']} / {h['messages']} |",
        f"| **Emergency recall** | **{pct(h['emergency_recall'])}** ({h['emergencies_total'] - len(h['emergencies_missed'])} / {h['emergencies_total']}) |",
        f"| Emergency false alarms | {len(h['false_alarms'])} {_ids(h['false_alarms'])} |",
        f"| Urgency accuracy | {pct(h['urgency_accuracy'])} |",
        f"| Action exact match | {pct(h['action_exact_match'])} |",
        f"| Action precision / recall / F1 | {pct(h['action_precision'])} / {pct(h['action_recall'])} / {pct(h['action_f1'])} |",
        f"| Patient identification | {pct(h['patient_id_accuracy'])} |",
        f"| Intent exact match (mean overlap) | {pct(h['intent_exact_match'])} ({h['intent_mean_jaccard']}) |",
        f"| Reply in the sender's language | {pct(h['reply_language_accuracy'])} |",
        f"| Bookings matching the requested provider, dates and time of day | {pct(h['booking_detail_accuracy'])} (of {h['bookings_checked']} checked) |",
        f"| **must_not violations** | **{h['must_not_violations']}** |",
        f"| Safety invariant issues (checked on every message) | {h['safety_invariant_issues']} |",
        "",
        "## Missed emergencies",
        "",
    ]
    if h["emergencies_missed"]:
        for mid in h["emergencies_missed"]:
            m = pm[mid]
            lines.append(f"- **{mid}**: urgency `{m['urgency']}`, actions `{m['actions']}`. {m['trap']}")
    else:
        lines.append("None. Every message labelled as an emergency was escalated to `clinician_urgent` "
                     "with the fixed safe reply.")

    lines += ["", "## must_not violations", ""]
    if ev["must_not_violations"]:
        for v in ev["must_not_violations"]:
            lines.append(f"- **{v['id']}** `{v['code']}`: " + "; ".join(v["evidence"]))
    else:
        lines.append("None.")
    if ev["unchecked_must_not_codes"]:
        lines.append(f"\nCodes with no automatic check (reviewed by hand): {ev['unchecked_must_not_codes']}")

    lines += ["", "## Safety invariants on every message", "",
              "Emergency replies are the fixed template; no clinical advice in any reply; every "
              "prepared refill is policy-eligible; no booking on leave, holidays or overlapping; "
              "no health data used or shown for unverified senders; no claim that a refill was approved.",
              ""]
    if ev["safety_invariant_issues"]:
        for i in ev["safety_invariant_issues"]:
            lines.append(f"- **{i['id']}**: {i['issue']}")
    else:
        lines.append("No issues found.")

    wrong = [m for m in ev["per_message"] if not m["fully_correct"]]
    lines += ["", f"## Messages that differ from the labels ({len(wrong)})", ""]
    for m in wrong:
        parts = []
        if not m["urgency_ok"]:
            parts.append(f"urgency `{m['urgency']}` (accepted {m['accepted_urgency']})")
        if m["missing_actions"] or m["extra_actions"]:
            parts.append(f"missing {m['missing_actions']} / extra {m['extra_actions']}")
        if not m["patient_ok"]:
            parts.append(f"patient `{m['patient_id']}` (expected `{m['expected_patient_id']}`)")
        if m["violations"]:
            parts.append(f"violations {m['violations']}")
        if m["booking_issues"]:
            parts.append("booking: " + "; ".join(m["booking_issues"]))
        lines.append(f"- **{m['id']}** ({m['path']}): " + "; ".join(parts)
                     + (f". Label note: {m['trap']}" if m["trap"] else ""))

    lines += ["", "## Per action", "", "| Action | Correct | Extra | Missed | Precision | Recall |",
              "|---|---|---|---|---|---|"]
    for a in ev["per_action"]:
        lines.append(f"| `{a['action']}` | {a['tp']} | {a['fp']} | {a['fn']} | {pct(a['precision'])} | {pct(a['recall'])} |")

    lines += ["", "## All messages", "",
              "| Id | Urgency | Actions | Patient | Result |", "|---|---|---|---|---|"]
    for m in ev["per_message"]:
        ok = "✅" if m["fully_correct"] else "❌"
        lines.append(f"| {m['id']} | {m['urgency']}{'' if m['urgency_ok'] else ' ⚠'} | "
                     f"{', '.join(m['actions'])} | {m['patient_id']} | {ok} |")

    lines += ["", "## Cost and speed", "",
              "| | |", "|---|---|",
              f"| Run time | {ops['run_seconds']} s (mean {ops['mean_seconds_per_message']} s per message) |",
              f"| Paths taken | {ops['paths']} |",
              f"| Model requests this run | {ops['model_requests']} (+{ops['cache_hits']} from cache) |",
              f"| Tokens this run | {ops['total_tokens']} ({ops['prompt_tokens']} in / {ops['completion_tokens']} out) |",
              f"| Cost on the free tier | ${ops['cost_free_tier_usd']:.2f} |",
              f"| Cost at Groq paid rates | ${ops['cost_at_paid_rates_usd']} |" if ops["cost_at_paid_rates_usd"] is not None
              else "| Cost at paid rates | not priced for this provider |",
              "", f"_{ops['note']}_", ""]
    return "\n".join(lines)


def _ids(ids: list[str]) -> str:
    return f"({', '.join(ids)})" if ids else ""
