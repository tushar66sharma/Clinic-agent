"""The agent: guard -> analyse (model) -> act (code, through MCP tools) -> reply (model).

Why this shape (docs/decisions/0006-planner-executor-agent.md): the free Groq tier allows
8,000 tokens per minute. A tool-calling loop that resends 16 tool schemas every turn needs
~5K tokens per turn and ~2 hours per 40-message run. Here the model is used where language
understanding is needed (once to analyse, once to write the reply) and code drives the tools,
so each message costs ~3K tokens, runs are repeatable, and policy cannot be talked around.

Every message ends with a result. If the model fails, the message is routed to a human.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..llm.base import LLMClient, LLMError, LLMTimeoutError
from . import guard as guard_mod
from .prompts import REPLY_SYSTEM_PROMPT, analysis_system_prompt, analysis_user_prompt
from .schemas import URGENCY_RANK, AgentResult, Analysis, AppointmentRequest, InboxMessage, ReplyDraft
from .tools_client import ToolSession

log = logging.getLogger(__name__)

ALL_MEDS_WORDS = ("all", "every", "todos", "todas")
CRISIS_LINE = ("If you ever feel unsafe or have thoughts of harming yourself, call or text 988, "
               "or call 911.")


@dataclass
class Context:
    msg: InboxMessage
    analysis: Analysis | None = None
    guard: guard_mod.GuardResult | None = None
    language: str = "English"
    intents: list[str] = field(default_factory=list)
    urgency: str = "routine"
    patient_id: str | None = None
    patient_name: str | None = None
    verified: bool = False
    relationship: str | None = None
    token: str | None = None
    profile: dict | None = None
    actions: list[str] = field(default_factory=list)
    routed: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    booked: bool = False
    third_party: bool = False
    notes: list[str] = field(default_factory=list)  # for the trace, not the patient
    path: str = "standard"

    def act(self, *actions: str) -> None:
        for a in actions:
            if a not in self.actions:
                self.actions.append(a)

    def route(self, queue: str) -> None:
        if queue not in self.routed:
            self.routed.append(queue)

    @property
    def sender_first_name(self) -> str:
        name = (self.msg.from_name or "").strip()
        return name.split()[0] if name else "there"


def fmt_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%A ") + str(d.day) + d.strftime(" %B")


def fmt_slot(s: dict) -> str:
    return f"{fmt_day(s['date'])} at {s['start']} with {s['provider_name']}"


class MessageProcessor:
    def __init__(self, tools: ToolSession, llm: LLMClient | None, today: date) -> None:
        self.tools = tools
        self.llm = llm
        self.today = today
        self._clinic_info: dict | None = None

    async def clinic_info(self) -> dict:
        if self._clinic_info is None:
            self._clinic_info = await self.tools.call("get_clinic_info")
        return self._clinic_info

    # ================================================================== entry point

    async def process(self, raw: dict) -> tuple[AgentResult, dict]:
        msg = InboxMessage.model_validate(raw)
        ctx = Context(msg=msg)
        self.tools.start_message()
        await self.tools.call("admin_set_clock", now=msg.received_at)
        llm_error: str | None = None

        ctx.guard = guard_mod.assess(msg.body)
        if ctx.guard.is_emergency:
            ctx.path = "emergency_fast_path"
            await self._emergency(ctx)
        else:
            try:
                ctx.analysis = await self._analyse(msg)
            except LLMError as exc:
                llm_error = f"{type(exc).__name__}: {exc}"
                log.warning("analysis failed for %s: %s", msg.id, llm_error)
            if ctx.analysis is None:
                ctx.path = "fallback_no_model"
                await self._fallback(ctx)
            elif ctx.analysis.urgency == "emergency":
                ctx.path = "emergency_model"
                await self._emergency(ctx)
            else:
                await self._standard(ctx)

        reply = await self._reply(ctx)
        if reply:
            await self.tools.call("draft_reply", message_id=msg.id, text=reply, language=ctx.language)

        result = AgentResult(
            id=msg.id, patient_id=ctx.patient_id, intents=ctx.intents or ["other"],
            urgency=ctx.urgency, actions=ctx.actions or ["no_action"], routed_to=ctx.routed,
            tool_calls=self.tools.tool_names, reply_draft=reply,
        )
        trace = {
            "id": msg.id, "path": ctx.path, "guard": vars(ctx.guard) if ctx.guard else None,
            "analysis": ctx.analysis.model_dump() if ctx.analysis else None,
            "verified": ctx.verified, "relationship": ctx.relationship, "facts": ctx.facts,
            "notes": ctx.notes, "llm_error": llm_error, "tool_trace": self.tools.calls,
        }
        return result, trace

    # ================================================================== model calls

    async def _analyse(self, msg: InboxMessage) -> Analysis | None:
        if self.llm is None:
            return None
        info = await self.clinic_info()
        # The provider client is blocking (and may sleep to respect rate limits), so it runs in
        # a worker thread to keep the event loop free for the web API and MCP traffic.
        return await _call_with_deadline(
            self.llm.complete_json,
            system=analysis_system_prompt(self.today, info),
            user=analysis_user_prompt(msg.model_dump()),
            schema=Analysis, role="analysis", max_tokens=1500,
        )

    async def _reply(self, ctx: Context) -> str:
        if ctx.path.startswith("emergency"):
            # Safety policy: emergency replies are a fixed template, never model-written.
            return guard_mod.emergency_reply(ctx.msg.from_name, ctx.language)
        if ctx.actions == ["no_action"]:
            return ""
        if self.llm is not None and ctx.path != "fallback_no_model":
            facts = "\n".join(f"- {f}" for f in ctx.facts) or "- We received the message."
            user = (f"language: {ctx.language}\nsender_first_name: {ctx.sender_first_name}\n"
                    f"facts:\n{facts}")
            for attempt in range(2):
                try:
                    draft = await _call_with_deadline(
                        self.llm.complete_json, system=REPLY_SYSTEM_PROMPT, user=user,
                        schema=ReplyDraft, role="reply", max_tokens=700)
                except LLMError as exc:
                    ctx.notes.append(f"reply model failed, used template: {exc}")
                    break
                problem = unfaithful(draft.reply, ctx.facts)
                if not problem:
                    return draft.reply.strip()
                ctx.notes.append(f"reply attempt {attempt + 1} rejected: {problem}")
                user += (f"\n\nYour previous reply was rejected: {problem}. Include every date "
                         "and time from the facts exactly, and no others.")
        return self._template_reply(ctx)

    def _template_reply(self, ctx: Context) -> str:
        body = " ".join(ctx.facts) or "We have received your message and our team will follow up."
        if ctx.language == "Spanish":
            return f"Hola {ctx.sender_first_name}, gracias por su mensaje. {body}\n\nMaplewood Family Clinic"
        return f"Hi {ctx.sender_first_name}, thank you for your message. {body}\n\nMaplewood Family Clinic"

    # ================================================================== identity

    async def _identify(self, ctx: Context) -> None:
        msg, a = ctx.msg, ctx.analysis
        contact = msg.from_contact or ""
        by_contact: list[dict] = []
        if contact:
            key = "email" if "@" in contact else "phone"
            res = await self.tools.call("find_patient", **{key: contact})
            by_contact = res.get("matches", []) if res.get("ok") else []

        subject = (a.subject_patient_name or "").strip() if a else ""
        sender_role = a.sender_role if a else "unknown"
        chosen: dict | None = None

        if subject and sender_role in ("caregiver", "third_party", "unknown"):
            chosen = _match_by_name(by_contact, subject)
            if chosen is None and len(subject.split()) >= 2:
                res = await self.tools.call("find_patient", name=subject)
                matches = res.get("matches", []) if res.get("ok") else []
                if len(matches) == 1:
                    chosen = matches[0]
        if chosen is None and by_contact:
            distinct = {m["patient_id"]: m for m in by_contact}
            if len(distinct) == 1:
                chosen = next(iter(distinct.values()))
            else:
                chosen = _match_by_name(list(distinct.values()), msg.from_name or "")
        if chosen is None and not by_contact and msg.from_name and sender_role != "organization":
            res = await self.tools.call("find_patient", name=msg.from_name)
            matches = res.get("matches", []) if res.get("ok") else []
            if len(matches) == 1:
                chosen = matches[0]
        if chosen is None:
            ctx.notes.append("no unique patient record identified")
            return

        ctx.patient_id, ctx.patient_name = chosen["patient_id"], chosen["name"]
        stated = msg.stated_dob or (a.stated_dob if a else None)
        v = await self.tools.call("verify_sender", patient_id=ctx.patient_id,
                                  from_name=msg.from_name, from_contact=msg.from_contact,
                                  stated_dob=stated)
        ctx.verified = bool(v.get("verified"))
        ctx.relationship = v.get("relationship")
        ctx.token = v.get("verification_token")
        ctx.notes.append(f"verification: {v.get('reason')}")
        if ctx.verified:
            ctx.profile = await self.tools.call("get_patient_profile", patient_id=ctx.patient_id,
                                                verification_token=ctx.token)

    # ================================================================== paths

    async def _emergency(self, ctx: Context) -> None:
        ctx.urgency = "emergency"
        ctx.language = ctx.analysis.language if ctx.analysis else guard_mod.detect_language(ctx.msg.body)
        if ctx.analysis:
            ctx.intents = list(dict.fromkeys(ctx.analysis.intents + ["clinical"]))
        else:
            ctx.intents = _fast_path_intents(ctx.msg.body)
        await self._identify(ctx)
        reason = ("Possible emergency: "
                  + (", ".join(ctx.guard.matches) if ctx.guard and ctx.guard.matches
                     else (ctx.analysis.urgency_reason if ctx.analysis else "flagged")))
        await self.tools.call("route_to_queue", message_id=ctx.msg.id, queue="clinician_urgent",
                              reason=reason[:300], priority="emergency", patient_id=ctx.patient_id)
        ctx.act("escalate_emergency")
        ctx.route("clinician_urgent")
        ctx.facts.append("Emergency template sent; clinician_urgent alerted.")

    async def _fallback(self, ctx: Context) -> None:
        """Model unavailable: never drop the message, hand it to a person."""
        ctx.language = guard_mod.detect_language(ctx.msg.body)
        ctx.intents = ["other"]
        await self._identify(ctx)
        if ctx.guard and ctx.guard.level == "urgent":
            ctx.urgency = "urgent"
            queue, action = "clinician_urgent", "route_to_clinician"
        else:
            queue, action = "front_desk", "route_to_front_desk"
        await self.tools.call("route_to_queue", message_id=ctx.msg.id, queue=queue,
                              reason="Automatic analysis unavailable; please review manually.",
                              priority=ctx.urgency, patient_id=ctx.patient_id)
        ctx.act(action)
        ctx.route(queue)
        ctx.facts.append("A member of our team will review your message and get back to you.")

    async def _standard(self, ctx: Context) -> None:
        a = ctx.analysis
        assert a is not None
        ctx.language = a.language or "English"
        ctx.intents = list(a.intents) or ["other"]
        ctx.urgency = a.urgency
        if ctx.guard and ctx.guard.level == "urgent" and URGENCY_RANK[ctx.urgency] < 1:
            ctx.urgency = "urgent"
            ctx.notes.append("urgency raised to urgent by guard: " + ", ".join(ctx.guard.matches))

        # Manipulation attempts are flagged whether or not the model noticed them, and a
        # flagged message is never dismissed as spam.
        injection = guard_mod.detect_injection(ctx.msg.body)
        suspicious = a.suspicious_instruction or injection
        if "spam" in ctx.intents and len(ctx.intents) == 1 and not suspicious:
            ctx.act("no_action")
            return
        if suspicious and ctx.intents == ["spam"]:
            ctx.intents = ["other"]

        await self._identify(ctx)

        # Someone unverified asking about a different named person is a third party, whatever
        # role the model guessed. (Verified caregivers are not affected.)
        subject = (a.subject_patient_name or "").strip()
        if subject and not ctx.verified and not _same_person(subject, ctx.msg.from_name or ""):
            ctx.third_party = True
            if "third_party" not in ctx.intents:
                ctx.intents.append("third_party")

        if suspicious:
            await self.tools.call("flag_suspicious_instruction", message_id=ctx.msg.id,
                                  excerpt=a.suspicious_instruction or injection,
                                  reason="Message tries to instruct the system or claims authority.")
            ctx.act("flag_suspicious_instruction")
            ctx.notes.append("suspicious instruction ignored; request handled under normal policy")

        # Someone not on file asking whether the clinic takes new patients is a prospective
        # patient, even if the model filed it as a general question.
        is_new_patient = ctx.patient_id is None and (
            "new_patient" in ctx.intents or "new_patients" in a.questions)
        # Verification is needed only for requests that read or change a patient's health or
        # appointment data. General questions, billing hand-offs and clinical concerns routed
        # to a clinician disclose nothing, so they proceed without it.
        needs_phi = bool(
            {"refill", "reschedule", "cancel", "records", "third_party"} & set(ctx.intents)
            or a.refill_medications or a.reschedule_to or a.cancel_date or a.records_request
            or a.admin_request or a.sender_role == "third_party"
            or (a.booking and not is_new_patient)
        )

        if needs_phi and not ctx.verified and not is_new_patient:
            await self._unverified(ctx)
        else:
            if ctx.verified:
                if "refill" in ctx.intents or a.refill_medications:
                    await self._refills(ctx)
                if a.booking and "new_patient" not in ctx.intents:
                    await self._book(ctx, a.booking)
                # A flagged manipulation attempt never drives cancellations or reschedules
                # ("cancel every appointment"): those destroy bookings and are left to staff.
                # Approval-gated actions (refill requests) and new bookings still follow policy.
                if suspicious and ("cancel" in ctx.intents or "reschedule" in ctx.intents):
                    ctx.facts.append("We could not act on the appointment changes in this message "
                                     "as written. A member of our team will review it.")
                    ctx.notes.append("cancel/reschedule skipped: message flagged as manipulation")
                else:
                    if "reschedule" in ctx.intents or a.reschedule_to:
                        await self._reschedule(ctx)
                    if "cancel" in ctx.intents:
                        await self._cancel(ctx)
                if a.records_request or "records" in ctx.intents:
                    await self._handoff(ctx, "front_desk", "route_to_front_desk",
                                        "Records request",
                                        "Our front desk team will process your records request.")
                if a.admin_request:
                    await self._handoff(ctx, "front_desk", "route_to_front_desk",
                                        f"Account change: {a.admin_request}",
                                        "Our front desk team will update your details and confirm.")
            await self._clinical(ctx)

        if is_new_patient:
            await self._new_patient(ctx)
        # Billing before general questions: a billing question also tagged "other" must go to
        # billing only, not to the front desk as well.
        if a.billing_question or "billing" in ctx.intents:
            await self._handoff(ctx, "billing", "route_to_billing", "Billing question",
                                "Our billing team will look into your question and contact you.")
        await self._questions(ctx)
        if not ctx.actions:
            if set(ctx.intents) <= {"other"}:
                ctx.act("acknowledge")
                ctx.facts.append("Thank the sender warmly; no action needed.")
            else:
                await self._handoff(ctx, "front_desk", "route_to_front_desk",
                                    "Request needs staff review",
                                    "A member of our team will review your message and follow up.")

    # ================================================================== handlers

    async def _unverified(self, ctx: Context) -> None:
        a = ctx.analysis
        third_party = (ctx.third_party or (a is not None and a.sender_role == "third_party")
                       or "third_party" in ctx.intents)
        if third_party:
            ctx.act("decline_disclosure")
            ctx.facts.append("We cannot share any information about another person's health or "
                             "appointments. The patient is welcome to contact us directly.")
            ctx.notes.append("sender not verified: no health or appointment information used")
            return

        # A health concern must not wait for verification: alerting a clinician discloses
        # nothing to the sender. (Found in manual testing: an unknown sender with a fever for
        # three days only got "please verify" and no clinician was alerted.)
        await self._clinician_for_unverified(ctx)

        ctx.act("request_verification")
        if ctx.patient_id is None:
            # No record matched, so this may be a new person or a patient writing from a new
            # number. Cover both without confirming whether any record exists.
            ctx.facts.append("If you are already a patient here, please verify your identity: reply "
                             "from the phone number or email on file, or give your full name and "
                             "date of birth. Do not confirm whether any record exists.")
            wants_visit = bool(a and (a.booking or "schedule" in ctx.intents))
            if wants_visit:
                await self._new_patient(ctx, intro="If you are new to the clinic, we are accepting "
                                                   "new patients.")
        else:
            ctx.facts.append("Before we can help with this request we need to verify identity: "
                             "please reply from the phone number or email on file, or give the "
                             "patient's full name and date of birth. Do not confirm whether any "
                             "record exists.")
        ctx.notes.append("sender not verified: no health or appointment information used")

    async def _clinician_for_unverified(self, ctx: Context) -> None:
        a = ctx.analysis
        mood = bool(ctx.guard and "low_mood" in ctx.guard.matches)
        concern = bool(a and (a.clinical_concern or "clinical" in ctx.intents)) or mood or bool(
            ctx.guard and ctx.guard.level == "urgent")
        if not concern:
            return
        urgent = URGENCY_RANK[ctx.urgency] >= 1 or mood
        queue = "clinician_urgent" if urgent else "clinician_routine"
        reason = (a.clinical_concern or a.urgency_reason) if a else "health concern"
        r = await self.tools.call("route_to_queue", message_id=ctx.msg.id, queue=queue,
                                  reason=f"Unverified sender, clinical: {reason}"[:300],
                                  priority="urgent" if urgent else "routine",
                                  patient_id=ctx.patient_id)
        if not r.get("ok"):
            ctx.notes.append(f"routing failed: {r.get('error')}")
            return
        ctx.act("route_to_clinician")
        ctx.route(queue)
        ctx.facts.append(f"A clinician will review your message {'today' if urgent else 'soon'}. "
                         "(Do not give any medical advice.)")
        if mood:
            ctx.facts.append(CRISIS_LINE)
        ctx.notes.append("clinical concern from an unverified sender routed to a clinician")

    async def _refills(self, ctx: Context) -> None:
        a = ctx.analysis
        queries = a.refill_medications if a and a.refill_medications else [""]
        if any(w in q.lower().split() for q in queries for w in ALL_MEDS_WORDS):
            queries = [""]  # "all my medications" = every active medication
        decisions: dict[str, dict] = {}
        for q in queries:
            res = await self.tools.call("check_refill_eligibility", patient_id=ctx.patient_id,
                                        verification_token=ctx.token, medication=q or None)
            if not res.get("ok"):
                ctx.notes.append(f"refill check failed: {res.get('error')}")
                continue
            if res.get("not_on_active_list"):
                await self._handoff(ctx, "provider_refills", "route_to_provider",
                                    f"Refill requested for {q!r}, not on active medication list",
                                    f"Your request for {q} has been passed to your provider to review.")
                continue
            for d in res["decisions"]:
                decisions[d["medication"]] = d

        for med, d in decisions.items():
            status = d["status"]
            if status == "eligible":
                r = await self.tools.call("prepare_refill_request", patient_id=ctx.patient_id,
                                          verification_token=ctx.token, medication=med,
                                          message_id=ctx.msg.id)
                if r.get("ok"):
                    ctx.act("prepare_refill_for_approval")
                    ctx.route("provider_refills")
                    ctx.facts.append(f"A refill request for {med} has been sent to the provider "
                                     "for approval. The pharmacy will be notified once it is approved.")
                else:
                    ctx.notes.append(f"prepare refused: {r.get('error')}")
            elif status in ("controlled_substance", "zero_refills"):
                why = ("it is a controlled medication that only the prescriber can renew"
                       if status == "controlled_substance" else "a new prescription is needed")
                await self._handoff(ctx, "provider_refills", "route_to_provider",
                                    f"{med}: {status}",
                                    f"Your {med} request has been sent to your provider to review, "
                                    f"because {why}.")
            elif status == "not_seen_12_months":
                ctx.act("refill_needs_visit")
                await self._handoff(ctx, "provider_refills", "route_to_provider",
                                    f"{med}: patient not seen in 12 months", None)
                slots = await self._slots("follow_up", self.today, self.today + timedelta(days=14),
                                          [self._primary(ctx), None], limit=3)
                ctx.facts.append(f"We can't renew {med} until you've had a visit, since your last "
                                 "visit was over a year ago. Your provider has been told about "
                                 "your request.")
                if slots:
                    ctx.act("offer_appointment")
                    ctx.facts.append("Available appointments: " + "; ".join(fmt_slot(s) for s in slots)
                                     + ". Reply to choose one.")
            elif status == "too_early":
                ctx.act("refill_too_early")
                ctx.facts.append(f"It is too early to refill {med}: your current supply lasts until "
                                 f"{fmt_day(d['run_out_date'])}. We can prepare the request from "
                                 f"{fmt_day(d['earliest_request_date'])}.")

    async def _clinical(self, ctx: Context) -> None:
        a = ctx.analysis
        if a is None:
            return
        mood = bool(ctx.guard and "low_mood" in ctx.guard.matches)
        # needs_clinician only counts with an actual health concern: a smaller model was seen
        # setting it on plain booking requests, sending them to clinicians for no reason.
        has_concern = bool(a.clinical_concern) or "clinical" in ctx.intents
        wants_clinician = (a.needs_clinician and has_concern) or mood or (
            "clinical" in ctx.intents and not ctx.booked and not a.booking)
        if not wants_clinician or ctx.booked:
            return
        if not ctx.verified and ctx.patient_id is None and "clinical" not in ctx.intents:
            return
        urgent = URGENCY_RANK[ctx.urgency] >= 1 or mood
        queue = "clinician_urgent" if urgent else "clinician_routine"
        await self.tools.call("route_to_queue", message_id=ctx.msg.id, queue=queue,
                              reason=f"Clinical: {a.clinical_concern or a.urgency_reason}"[:300],
                              priority="urgent" if urgent else "routine", patient_id=ctx.patient_id)
        ctx.act("route_to_clinician")
        ctx.route(queue)
        when = "today" if urgent else "soon"
        ctx.facts.append(f"A clinician will review your message {when} and contact you. "
                         "(Do not give any medical advice.)")
        if mood:
            ctx.facts.append(CRISIS_LINE)

    def _primary(self, ctx: Context) -> str | None:
        return (ctx.profile or {}).get("primary_provider")

    async def _slots(self, visit_type: str, start: date, end: date, providers: list[str | None],
                     part_of_day: str = "any", limit: int = 3) -> list[dict]:
        for provider in providers:
            res = await self.tools.call("find_free_slots", visit_type=visit_type,
                                        date_from=start.isoformat(), date_to=end.isoformat(),
                                        provider=provider, part_of_day=part_of_day, limit=limit)
            if res.get("ok") and res["slots"]:
                return res["slots"]
        return []

    def _window(self, req: AppointmentRequest) -> tuple[date, date]:
        start = _parse(req.date_from) or self.today
        start = max(start, self.today)
        if req.date_to:
            end = _parse(req.date_to) or start
        elif req.visit_type == "sick_visit" and not req.date_from:
            end = self._next_business_day(self.today)
        elif req.date_from:
            end = start
        else:
            end = start + timedelta(days=14)
        return start, max(end, start)

    def _next_business_day(self, d: date) -> date:
        holidays = set((self._clinic_info or {}).get("holidays", []))
        nxt = d + timedelta(days=1)
        while nxt.weekday() >= 5 or nxt.isoformat() in holidays:
            nxt += timedelta(days=1)
        return nxt

    async def _book(self, ctx: Context, req: AppointmentRequest) -> None:
        if req.visit_type is None:
            req = req.model_copy(update={"visit_type": "follow_up"})
            ctx.notes.append("visit type not stated: assumed follow_up")
        start, end = self._window(req)
        if req.exact_time and req.provider:
            r = await self.tools.call("book_appointment", patient_id=ctx.patient_id,
                                      verification_token=ctx.token, provider=req.provider,
                                      date=start.isoformat(), start=req.exact_time,
                                      visit_type=req.visit_type, message_id=ctx.msg.id)
            if r.get("ok"):
                return self._booked(ctx, r["appointment"])
            violations = (r.get("error") or {}).get("violations", [])
            reason = _violation_text(violations)
            # Offer the times closest to the one requested, same provider and day first.
            same_day = await self._slots(req.visit_type, start, start, [req.provider], limit=20)
            same_day.sort(key=lambda s: abs(_minutes(s["start"]) - _minutes(req.exact_time)))
            alts = same_day[:3]
            if len(alts) < 3:
                later = await self._slots(req.visit_type, start + timedelta(days=1),
                                          start + timedelta(days=14), [req.provider, None], limit=3)
                alts += later[: 3 - len(alts)]
            return self._alternatives(ctx, f"{fmt_day(start.isoformat())} at {req.exact_time} is not "
                                           f"available ({reason}).", alts)

        providers = [req.provider] if req.provider else [self._primary(ctx), None]
        slots = await self._slots(req.visit_type, start, end, providers, req.part_of_day)
        for slot in slots:
            r = await self.tools.call("book_appointment", patient_id=ctx.patient_id,
                                      verification_token=ctx.token, provider=slot["provider"],
                                      date=slot["date"], start=slot["start"],
                                      visit_type=req.visit_type, message_id=ctx.msg.id)
            if r.get("ok"):
                return self._booked(ctx, r["appointment"])

        # Nothing in the requested window with the requested provider: offer alternatives.
        notes = await self.tools.call("find_free_slots", visit_type=req.visit_type,
                                      date_from=start.isoformat(), date_to=end.isoformat(),
                                      provider=req.provider, part_of_day=req.part_of_day, limit=1)
        why = "; ".join(notes.get("notes", [])) or "no free slots match the request"
        alts = await self._slots(req.visit_type, start, end, [None], req.part_of_day)
        if req.provider:
            later = await self._slots(req.visit_type, end + timedelta(days=1),
                                      end + timedelta(days=21), [req.provider], limit=2)
            alts = alts[:2] + later
        self._alternatives(ctx, f"The requested time is not available ({why}).", alts)

    def _booked(self, ctx: Context, appt: dict, rescheduled_from: dict | None = None) -> None:
        ctx.booked = True
        visit = appt["visit_type"].replace("_", " ")
        when = f"{fmt_day(appt['date'])} at {appt['start']} with {appt['provider_name']}"
        if rescheduled_from:
            ctx.act("reschedule_appointment")
            ctx.facts.append(f"Your {visit} has been moved from {fmt_day(rescheduled_from['date'])} "
                             f"at {rescheduled_from['start']} to {when}.")
        else:
            ctx.act("book_appointment")
            ctx.facts.append(f"Booked: {visit} on {when}.")

    def _alternatives(self, ctx: Context, reason: str, alts: list[dict]) -> None:
        ctx.act("offer_alternatives")
        if alts:
            ctx.facts.append(reason + " Available options: " + "; ".join(fmt_slot(s) for s in alts)
                             + ". Reply to choose one.")
        else:
            ctx.facts.append(reason + " Our front desk will contact you with options.")

    async def _reschedule(self, ctx: Context) -> None:
        a = ctx.analysis
        frm = _parse(a.reschedule_from_date) if a else None
        res = await self.tools.call("list_appointments", patient_id=ctx.patient_id,
                                    verification_token=ctx.token,
                                    date_from=frm.isoformat() if frm else None,
                                    date_to=frm.isoformat() if frm else None)
        appts = res.get("appointments", []) if res.get("ok") else []
        if a and a.reschedule_from_description and len(appts) > 1:
            words = a.reschedule_from_description.lower().replace("_", " ")
            narrowed = [x for x in appts if x["visit_type"].replace("_", " ") in words
                        or x["provider"].lower() in words]
            appts = narrowed or appts
        if len(appts) != 1:
            ctx.act("acknowledge")
            ctx.facts.append("We could not tell which appointment to move" +
                             (": " + "; ".join(f"{fmt_day(x['date'])} at {x['start']} with "
                                               f"{x['provider_name']}" for x in appts) if appts else "")
                             + ". Please reply with the date and time of the appointment to move.")
            return
        appt = appts[0]
        target = a.reschedule_to if a and a.reschedule_to else AppointmentRequest(
            visit_type=appt["visit_type"], provider=None, date_from=None, date_to=None,
            part_of_day="any", exact_time=None)
        start, end = self._window(target)
        provider = target.provider or appt["provider"]
        slots = await self._slots(appt["visit_type"], start, end, [provider], target.part_of_day,
                                  limit=3)
        if target.exact_time:
            slots = [s for s in slots if s["start"] == target.exact_time] or slots
        for slot in slots:
            r = await self.tools.call("reschedule_appointment", appointment_id=appt["appointment_id"],
                                      patient_id=ctx.patient_id, verification_token=ctx.token,
                                      new_date=slot["date"], new_start=slot["start"],
                                      message_id=ctx.msg.id,
                                      new_provider=None if slot["provider"] == appt["provider"]
                                      else slot["provider"])
            if r.get("ok"):
                return self._booked(ctx, r["appointment"], rescheduled_from=appt)
        alts = await self._slots(appt["visit_type"], start, end, [None], target.part_of_day)
        self._alternatives(ctx, f"We could not find a matching time with {appt['provider_name']}; "
                                "your current appointment is unchanged.", alts)

    async def _cancel(self, ctx: Context) -> None:
        a = ctx.analysis
        day = _parse(a.cancel_date) if a else None
        res = await self.tools.call("list_appointments", patient_id=ctx.patient_id,
                                    verification_token=ctx.token,
                                    date_from=day.isoformat() if day else None,
                                    date_to=day.isoformat() if day else None)
        appts = res.get("appointments", []) if res.get("ok") else []
        if len(appts) == 1:
            appt = appts[0]
            r = await self.tools.call("cancel_appointment", appointment_id=appt["appointment_id"],
                                      patient_id=ctx.patient_id, verification_token=ctx.token,
                                      message_id=ctx.msg.id)
            if r.get("ok"):
                ctx.act("cancel_appointment")
                ctx.facts.append(f"Your appointment on {fmt_day(appt['date'])} at {appt['start']} "
                                 f"with {appt['provider_name']} has been cancelled. "
                                 "Reply any time to rebook.")
                return
        if len(appts) > 1:
            # Design call: never guess which appointment to cancel.
            ctx.act("acknowledge")
            if day:
                listing = "; ".join(f"{x['start']} with {x['provider_name']}" for x in appts)
                ctx.facts.append(f"You have more than one appointment on {fmt_day(day.isoformat())}: "
                                 f"{listing}. Please reply to tell us which one to cancel, or both.")
            else:
                # No date given: the appointments are on different days, so name each date.
                listing = "; ".join(f"{fmt_day(x['date'])} at {x['start']} with {x['provider_name']}"
                                    for x in appts)
                ctx.facts.append(f"You have several upcoming appointments: {listing}. "
                                 "Please reply to tell us which one to cancel.")
            ctx.notes.append("ambiguous cancellation: asked the patient instead of guessing")
        else:
            ctx.act("acknowledge")
            ctx.facts.append("We could not find an appointment on that date. Please reply with "
                             "the date and time of the appointment you want to cancel.")

    async def _new_patient(self, ctx: Context, intro: str = "Yes, the clinic is accepting new "
                                                             "patients.") -> None:
        ctx.act("answer_directly", "offer_new_patient_booking")
        req = ctx.analysis.booking if ctx.analysis else None
        requested = _parse(req.date_from) if req else None
        start = max(requested or self.today, self._next_business_day(self.today))
        slots = await self._slots("new_patient", start, start + timedelta(days=14), [None], limit=3)
        ctx.facts.append(f"{intro} A first visit is a 40-minute new-patient appointment.")
        if slots:
            ctx.facts.append("Available new-patient appointments: " + "; ".join(fmt_slot(s) for s in slots)
                             + ". Reply with your preferred time, full name and date of birth to book.")

    async def _questions(self, ctx: Context) -> None:
        a = ctx.analysis
        if a is None:
            return
        for q in a.questions:
            if q == "clinic_hours":
                info = await self.clinic_info()
                h = info["hours"]
                ctx.act("answer_directly")
                ctx.facts.append(f"Clinic hours: Monday to Friday, {h['open']} to {h['close']}, closed "
                                 f"for lunch {h['lunch'][0]} to {h['lunch'][1]}, and closed on holidays.")
            elif q == "open_on_date" and _parse(a.question_date):
                r = await self.tools.call("check_clinic_open", date=a.question_date)
                if r.get("ok"):
                    ctx.act("answer_directly")
                    if r["open"]:
                        ctx.facts.append(f"Yes, the clinic is open on {fmt_day(r['date'])}, "
                                         f"{r['hours']['open']} to {r['hours']['close']}.")
                    else:
                        # State the real next open day, so the reply writer never has to guess
                        # (it once claimed "open the following day" when that was a holiday too).
                        reopen = self._next_business_day(date.fromisoformat(r["date"]))
                        ctx.facts.append(f"The clinic is closed on {fmt_day(r['date'])} "
                                         f"({r['closed_reason']}). The next day the clinic is "
                                         f"open is {fmt_day(reopen.isoformat())}.")
            elif q == "new_patients" and "offer_new_patient_booking" not in ctx.actions:
                ctx.act("answer_directly")
                ctx.facts.append("Yes, the clinic is accepting new patients.")
            elif q == "other" and not ctx.actions:
                await self._handoff(ctx, "front_desk", "route_to_front_desk", "General question",
                                    "Our front desk team will answer your question shortly.")

    async def _handoff(self, ctx: Context, queue: str, action: str, reason: str,
                       fact: str | None) -> None:
        priority = "urgent" if URGENCY_RANK[ctx.urgency] >= 1 else "routine"
        r = await self.tools.call("route_to_queue", message_id=ctx.msg.id, queue=queue,
                                  reason=reason[:300], priority=priority, patient_id=ctx.patient_id)
        if r.get("ok"):
            ctx.act(action)
            ctx.route(queue)
            if fact:
                ctx.facts.append(fact)
        else:
            ctx.notes.append(f"routing failed: {r.get('error')}")


# ====================================================================== helpers

DEFAULT_LLM_DEADLINE_SECONDS = 240.0


async def _call_with_deadline(fn, /, **kwargs):
    """Run a blocking provider call in a worker thread with a hard wall-clock deadline.

    Why: live runs showed single Groq requests hanging for 6-13 minutes despite the HTTP
    timeout. A message must never sit that long, so past the deadline the call is abandoned
    and the caller's normal failure path runs (analysis -> hand to a human; reply -> template).
    The abandoned thread may still finish in the background; its result is ignored.
    Deadline: LLM_DEADLINE_SECONDS (default 240 s, enough for ordinary rate-limit retries).
    """
    deadline = float(os.getenv("LLM_DEADLINE_SECONDS", DEFAULT_LLM_DEADLINE_SECONDS))
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, **kwargs), timeout=deadline)
    except TimeoutError as exc:
        log.warning("AI call exceeded the %.0fs deadline; falling back", deadline)
        raise LLMTimeoutError(f"AI call exceeded the {deadline:.0f}s deadline") from exc


TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
DAY_RE = re.compile(r"\b(\d{1,2}) (January|February|March|April|May|June|July|August|September|"
                    r"October|November|December)\b")


def _times(text: str) -> set[str]:
    return {f"{int(h)}:{m}" for h, m in TIME_RE.findall(text)}


def unfaithful(reply: str, facts: list[str]) -> str | None:
    """Return why a model-written reply misstates the facts, or None if it is faithful.

    Every time in the facts must appear in the reply and no other times may appear; every
    day-of-month from the facts must appear. This catches dropped or invented appointments.
    Day numbers are checked as numbers, so it works for replies in any language.
    """
    if not reply.strip():
        return "empty reply"
    fact_text = " ".join(facts)
    missing = _times(fact_text) - _times(reply)
    extra = _times(reply) - _times(fact_text)
    if missing:
        return f"missing times {sorted(missing)}"
    if extra:
        return f"times not in the facts {sorted(extra)}"
    fact_days = {str(int(d)) for d, _ in DAY_RE.findall(fact_text)}
    reply_numbers = {str(int(n)) for n in re.findall(r"\b\d{1,2}\b", TIME_RE.sub(" ", reply))}
    if fact_days - reply_numbers:
        return f"missing dates {sorted(fact_days - reply_numbers)}"
    return None


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _same_person(a: str, b: str) -> bool:
    x, y = a.lower().split(), b.lower().split()
    if not x or not y:
        return False
    return x == y or (len(x) == 1 and x[0] == y[0]) or (len(y) == 1 and y[0] == x[0])


def _parse(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _match_by_name(matches: list[dict], name: str) -> dict | None:
    """Pick the match whose name equals `name`, or whose first name equals a one-word name."""
    target = name.lower().split()
    if not target:
        return None
    for m in matches:
        parts = m["name"].lower().split()
        if parts == target or (len(target) == 1 and parts and parts[0] == target[0]):
            return m
    return None


def _fast_path_intents(body: str) -> list[str]:
    intents = ["clinical"]
    if re.search(r"refill|prescription|script|more (of )?my|medication|receta", body.lower()):
        intents.insert(0, "refill")
    return intents


def _violation_text(violations: list[str]) -> str:
    text = {
        "provider_already_booked": "that time is already booked",
        "provider_on_leave": "the provider is on leave that day",
        "clinic_holiday": "the clinic is closed for a holiday",
        "clinic_closed_that_day": "the clinic is closed that day",
        "overlaps_lunch": "that is during the lunch break",
        "outside_opening_hours": "that is outside opening hours",
        "start_not_on_20_minute_grid": "appointments start on the hour or at :20 or :40",
        "in_the_past": "that time has passed",
        "outside_known_schedule": "the schedule is not open that far ahead",
    }
    return "; ".join(text.get(v, v) for v in violations) or "not available"

