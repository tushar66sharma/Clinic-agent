"""Scoring a run against labels.

Definitions (also in docs/testing.md):
- Urgency correct: predicted urgency is in the label's `accepted_urgency`.
- Emergency set: labels whose expected actions include `escalate_emergency`.
  Emergency recall = share of that set where the agent took `escalate_emergency`.
- False alarm: `escalate_emergency` on a message whose label does not accept "emergency".
- Action exact match: predicted action set == expected action set.
  Micro precision/recall/F1 are computed over all (message, action) pairs.
- Patient correct: predicted patient_id == label patient_id (both may be null).
- Intent exact match and Jaccard overlap between predicted and labelled intent sets.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from ..agent.guard import detect_language
from ..clinic.repository import ClinicRepository
from .checks import appointment_detail_issues, build_world, check_must_not, global_invariants

# Groq on-demand prices per million tokens, from the model pages on 2026-10-18.
# Used only to estimate what a run would cost beyond the free tier.
PRICES_PER_MILLION = {
    "openai/gpt-oss-120b": {"input": 0.15, "output": 0.60},
    "openai/gpt-oss-20b": {"input": 0.075, "output": 0.30},
}


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def evaluate(results: list[dict], labels: list[dict], traces: list[dict], run_log: dict,
             summary: dict, repo: ClinicRepository, today: date,
             messages: list[dict] | None = None, details: dict | None = None) -> dict:
    res = {r["id"]: r for r in results}
    tr = {t["id"]: t for t in traces}
    bodies = {m["id"]: m["body"] for m in (messages or [])}
    world = build_world(repo, traces)

    per_message, violations, invariant_issues, unchecked = [], [], [], set()
    action_counts = {"tp": Counter(), "fp": Counter(), "fn": Counter()}
    missing_results = []

    for lab in labels:
        mid = lab["id"]
        r = res.get(mid)
        if r is None:
            missing_results.append(mid)
            continue
        t = tr.get(mid, {})
        exp, got = set(lab["expected_actions"]), set(r["actions"])
        for a in exp & got:
            action_counts["tp"][a] += 1
        for a in got - exp:
            action_counts["fp"][a] += 1
        for a in exp - got:
            action_counts["fn"][a] += 1

        msg_violations = []
        for code in lab.get("must_not", []):
            ev = check_must_not(code, r, t, world, run_log, bodies.get(mid, ""))
            if ev is None:
                unchecked.add(code)
            elif ev:
                msg_violations.append({"id": mid, "code": code, "evidence": ev})
        violations += msg_violations

        inv = global_invariants(r, t, lab, world, run_log, today, bodies.get(mid, ""))
        invariant_issues += [{"id": mid, "issue": i} for i in inv]

        booking_issues = appointment_detail_issues(mid, (details or {}).get(mid), world)

        li, pi = set(lab["intents"]), set(r["intents"])
        is_emergency = "escalate_emergency" in exp
        escalated = "escalate_emergency" in got
        lang_expected = detect_language(bodies[mid]) if mid in bodies else None
        lang_reply = detect_language(r["reply_draft"]) if r["reply_draft"] else None
        per_message.append({
            "id": mid,
            "urgency": r["urgency"], "accepted_urgency": lab["accepted_urgency"],
            "urgency_ok": r["urgency"] in lab["accepted_urgency"],
            "expected_actions": sorted(exp), "actions": r["actions"],
            "actions_exact": exp == got, "missing_actions": sorted(exp - got),
            "extra_actions": sorted(got - exp),
            "patient_id": r["patient_id"], "expected_patient_id": lab["patient_id"],
            "patient_ok": r["patient_id"] == lab["patient_id"],
            "intents": r["intents"], "expected_intents": lab["intents"],
            "intents_exact": li == pi,
            "intents_jaccard": round(len(li & pi) / len(li | pi), 3) if li | pi else 1.0,
            "emergency_label": is_emergency, "escalated": escalated,
            "false_alarm": escalated and "emergency" not in lab["accepted_urgency"],
            "reply_language_ok": (lang_reply == lang_expected) if lang_expected and lang_reply else None,
            "violations": [v["code"] for v in msg_violations],
            "booking_checked": bool((details or {}).get(mid, {}).get("appointment")),
            "booking_issues": booking_issues,
            "invariant_issues": inv,
            "trap": lab.get("trap", ""),
            "path": t.get("path"), "seconds": t.get("seconds"),
            "fully_correct": (r["urgency"] in lab["accepted_urgency"] and exp == got
                              and r["patient_id"] == lab["patient_id"] and not msg_violations
                              and not booking_issues),
        })

    n = len(per_message)
    emerg = [m for m in per_message if m["emergency_label"]]
    escal = [m for m in per_message if m["escalated"]]
    tp, fp, fn = (sum(action_counts[k].values()) for k in ("tp", "fp", "fn"))
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision and recall else None
    all_actions = sorted(set().union(*action_counts.values()))
    lang = [m for m in per_message if m["reply_language_ok"] is not None]
    booked = [m for m in per_message if m["booking_checked"]]

    return {
        "headline": {
            "messages": n,
            "fully_correct": sum(m["fully_correct"] for m in per_message),
            "urgency_accuracy": _ratio(sum(m["urgency_ok"] for m in per_message), n),
            "emergency_recall": _ratio(sum(m["escalated"] for m in emerg), len(emerg)),
            "emergencies_total": len(emerg),
            "emergencies_missed": [m["id"] for m in emerg if not m["escalated"]],
            "false_alarms": [m["id"] for m in per_message if m["false_alarm"]],
            "emergency_precision": _ratio(sum(not m["false_alarm"] for m in escal), len(escal)),
            "action_exact_match": _ratio(sum(m["actions_exact"] for m in per_message), n),
            "action_precision": precision, "action_recall": recall, "action_f1": f1,
            "patient_id_accuracy": _ratio(sum(m["patient_ok"] for m in per_message), n),
            "intent_exact_match": _ratio(sum(m["intents_exact"] for m in per_message), n),
            "intent_mean_jaccard": round(sum(m["intents_jaccard"] for m in per_message) / n, 3) if n else None,
            "reply_language_accuracy": _ratio(sum(m["reply_language_ok"] for m in lang), len(lang)),
            "booking_detail_accuracy": _ratio(sum(not m["booking_issues"] for m in booked), len(booked)),
            "bookings_checked": len(booked),
            "must_not_violations": len(violations),
            "safety_invariant_issues": len(invariant_issues),
        },
        "must_not_violations": violations,
        "safety_invariant_issues": invariant_issues,
        "unchecked_must_not_codes": sorted(unchecked),
        "missing_results": missing_results,
        "per_action": [
            {"action": a, "tp": action_counts["tp"][a], "fp": action_counts["fp"][a],
             "fn": action_counts["fn"][a],
             "precision": _ratio(action_counts["tp"][a], action_counts["tp"][a] + action_counts["fp"][a]),
             "recall": _ratio(action_counts["tp"][a], action_counts["tp"][a] + action_counts["fn"][a])}
            for a in all_actions
        ],
        "per_message": per_message,
        "operations": _operations(summary, traces),
    }


def _operations(summary: dict, traces: list[dict]) -> dict:
    usage = summary.get("usage") or {}
    cost = 0.0
    priced = True
    for model, u in (usage.get("by_model") or {}).items():
        price = PRICES_PER_MILLION.get(model)
        if price is None:
            priced = False
            continue
        cost += u["prompt_tokens"] / 1e6 * price["input"] + u["completion_tokens"] / 1e6 * price["output"]
    secs = [t.get("seconds") or 0 for t in traces]
    return {
        "provider": summary.get("provider"), "models": summary.get("models"),
        "run_seconds": summary.get("seconds"),
        "mean_seconds_per_message": round(sum(secs) / len(secs), 2) if secs else None,
        "paths": summary.get("paths"),
        "model_requests": usage.get("requests"), "cache_hits": usage.get("cache_hits"),
        "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cost_free_tier_usd": 0.0,
        "cost_at_paid_rates_usd": round(cost, 4) if priced else None,
        "note": ("Token counts cover only model calls made in this run; cached responses cost nothing. "
                 "Run with LLM_CACHE=0 for a full-cost measurement."),
    }
