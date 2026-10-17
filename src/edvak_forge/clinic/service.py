"""ClinicService: the operations behind every MCP tool.

Every method returns a JSON-serialisable dict:
    {"ok": True, ...data...}                      on success
    {"ok": False, "error": {"code", "message"}}   on a handled failure

Methods never raise for expected problems (unknown patient, slot taken, not verified), because
the agent must be able to read the reason and recover, for example by offering alternatives.

Privacy is enforced HERE, not in the prompt: tools that return or change a patient's health or
appointment data require a `verification_token`, which `verify_sender` issues only after the
sender passes the clinic's verification rule. See docs/security.md.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from . import identity, refills, scheduling
from .repository import ClinicRepository

PRIORITIES = ("emergency", "urgent", "routine")


def _err(code: str, message: str, **extra: Any) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, **extra}}


def _parse_date(value: str | None, field_name: str) -> tuple[date | None, dict | None]:
    if value is None or value == "":
        return None, None
    try:
        return date.fromisoformat(value), None
    except (TypeError, ValueError):
        return None, _err("invalid_date", f"{field_name} must be YYYY-MM-DD, got {value!r}.")


@dataclass
class Grant:
    """Proof that a sender was verified for one patient during this run."""
    patient_id: str
    relationship: str
    method: str


@dataclass
class RunLog:
    """Everything the agent produced during a run, for staff queues and the evaluation."""
    queue_tickets: list[dict] = field(default_factory=list)
    refill_requests: list[dict] = field(default_factory=list)
    reply_drafts: list[dict] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)
    appointment_changes: list[dict] = field(default_factory=list)


class ClinicService:
    def __init__(self, repo: ClinicRepository, today: date) -> None:
        self.repo = repo
        self.today = today
        self.log = RunLog()
        self._grants: dict[str, Grant] = {}
        # Simulated "now". The agent harness sets it to each message's received_at so that
        # same-day slots that have already passed are never offered or booked.
        self.now: datetime | None = None

    def set_clock(self, now: str | None) -> dict:
        """Harness-only (not offered to the model): set the simulated current time."""
        if not now:
            self.now = None
            return {"ok": True, "now": None}
        try:
            parsed = datetime.fromisoformat(now)
        except ValueError:
            return _err("invalid_datetime", "now must be ISO format.")
        # Clinic times are local wall-clock times, so drop the UTC offset after parsing.
        self.now = parsed.replace(tzinfo=None)
        return {"ok": True, "now": self.now.isoformat()}

    # ------------------------------------------------------------------ identity

    def find_patient(
        self, name: str | None = None, phone: str | None = None, email: str | None = None,
        dob: str | None = None,
    ) -> dict:
        if not any([name, phone, email, dob]):
            return _err("missing_search_fields", "Give at least one of name, phone, email, dob.")
        dob_d, error = _parse_date(dob, "dob")
        if error:
            return error
        matches = identity.find_patients(
            self.repo.patients, name=name, phone=phone, email=email, dob=dob_d
        )
        return {
            "ok": True,
            "matches": [m.to_dict() for m in matches],
            "note": "Matches only identify a record. Call verify_sender before using or "
                    "disclosing any health or appointment information.",
        }

    def verify_sender(
        self, patient_id: str, from_name: str | None, from_contact: str | None,
        stated_dob: str | None = None,
    ) -> dict:
        patient = self.repo.patient(patient_id)
        if patient is None:
            return _err("patient_not_found", f"No patient with id {patient_id}.")
        dob_d, error = _parse_date(stated_dob, "stated_dob")
        if error:
            return error
        result = identity.verify_sender(
            patient, from_name=from_name, from_contact=from_contact, stated_dob=dob_d
        )
        response: dict[str, Any] = {"ok": True, "patient_id": patient_id, **result.to_dict()}
        if result.verified:
            token = secrets.token_hex(8)
            self._grants[token] = Grant(patient_id, result.relationship, result.method or "")
            response["verification_token"] = token
        else:
            response["instruction"] = (
                "Sender is NOT verified. Do not disclose or change any health or appointment "
                "information for this patient. Use request_verification or decline_disclosure."
            )
        return response

    def _require_grant(self, patient_id: str, token: str | None) -> dict | None:
        grant = self._grants.get(token or "")
        if grant is None or grant.patient_id != patient_id:
            return _err(
                "verification_required",
                "A valid verification_token for this patient is required. Call verify_sender "
                "first. Unverified senders must not receive health or appointment details.",
            )
        return None

    def get_patient_profile(self, patient_id: str, verification_token: str) -> dict:
        if error := self._require_grant(patient_id, verification_token):
            return error
        p = self.repo.patient(patient_id)
        assert p is not None  # a grant only exists for real patients
        provider = self.repo.clinic.provider(p.primary_provider)
        caregiver = p.authorised_caregiver
        return {
            "ok": True,
            "patient_id": p.id,
            "name": p.name,
            "first_name": p.name.split()[0],
            "age": _age(p.dob, self.today),
            "primary_provider": p.primary_provider,
            "primary_provider_name": provider.name if provider else None,
            "last_visit": p.last_visit.isoformat(),
            "preferred_language": p.preferred_language,
            "authorised_caregiver": (
                {"name": caregiver.name, "relationship": caregiver.relationship}
                if caregiver else None
            ),
        }

    # ------------------------------------------------------------------ medications

    def get_medications(self, patient_id: str, verification_token: str) -> dict:
        if error := self._require_grant(patient_id, verification_token):
            return error
        meds = self.repo.medications_for(patient_id)
        return {
            "ok": True,
            "patient_id": patient_id,
            "medications": [
                {
                    "medication": m.medication,
                    "controlled_schedule": m.controlled_schedule,
                    "run_out_date": refills.run_out_date(m).isoformat(),
                    "refills_remaining": m.refills_remaining,
                    "prescriber": m.prescriber,
                }
                for m in meds
            ],
        }

    def check_refill_eligibility(
        self, patient_id: str, verification_token: str, medication: str | None = None
    ) -> dict:
        if error := self._require_grant(patient_id, verification_token):
            return error
        patient = self.repo.patient(patient_id)
        assert patient is not None
        meds = self.repo.medications_for(patient_id)
        matched = refills.match_medications(meds, medication)
        if not matched:
            return {
                "ok": True,
                "patient_id": patient_id,
                "decisions": [],
                "not_on_active_list": True,
                "active_medications": [m.medication for m in meds],
                "recommended_actions": ["route_to_provider"],
                "recommended_queue": "provider_refills",
                "explanation": f"{medication!r} is not on the patient's active medication list. "
                               "Do not prepare a refill; route to the provider.",
            }
        return {
            "ok": True,
            "patient_id": patient_id,
            "decisions": [refills.check_refill(m, patient, self.today).to_dict() for m in matched],
        }

    def prepare_refill_request(
        self, patient_id: str, verification_token: str, medication: str, message_id: str
    ) -> dict:
        """Create a refill request for PROVIDER APPROVAL. Refuses anything not fully eligible."""
        if error := self._require_grant(patient_id, verification_token):
            return error
        patient = self.repo.patient(patient_id)
        assert patient is not None
        matched = refills.match_medications(self.repo.medications_for(patient_id), medication)
        if len(matched) != 1:
            return _err(
                "medication_not_identified",
                f"Expected exactly one matching medication for {medication!r}, "
                f"found {len(matched)}. Name the medication exactly.",
            )
        decision = refills.check_refill(matched[0], patient, self.today)
        if not decision.eligible:
            return _err(
                "refill_not_eligible",
                f"Refill cannot be prepared: {decision.status}. {decision.explanation}",
                decision=decision.to_dict(),
            )
        # Duplicate protection: one pending request per patient + medication per run.
        for existing in self.log.refill_requests:
            if existing["patient_id"] == patient_id and existing["medication"] == decision.medication:
                return {"ok": True, "refill_request": existing, "duplicate": True}
        request = {
            "request_id": f"RR{len(self.log.refill_requests) + 1:03d}",
            "message_id": message_id,
            "patient_id": patient_id,
            "medication": decision.medication,
            "prescriber": decision.prescriber,
            "status": "pending_provider_approval",
            "queue": "provider_refills",
        }
        self.log.refill_requests.append(request)
        return {"ok": True, "refill_request": request, "duplicate": False}

    # ------------------------------------------------------------------ appointments

    def list_appointments(
        self, patient_id: str, verification_token: str, date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        if error := self._require_grant(patient_id, verification_token):
            return error
        start, e1 = _parse_date(date_from, "date_from")
        end, e2 = _parse_date(date_to, "date_to")
        if e1 or e2:
            return e1 or e2  # type: ignore[return-value]
        start = start or self.today
        appts = [
            a for a in self.repo.booked_appointments()
            if a.patient_id == patient_id and a.date >= start and (end is None or a.date <= end)
        ]
        appts.sort(key=lambda a: (a.date, a.start))
        return {"ok": True, "patient_id": patient_id,
                "appointments": [self._appt_view(a) for a in appts]}

    def find_free_slots(
        self, visit_type: str, date_from: str, date_to: str, provider: str | None = None,
        part_of_day: str = "any", not_before: str | None = None, limit: int = 8,
    ) -> dict:
        if visit_type not in self.repo.clinic.visit_types:
            return _err("unknown_visit_type",
                        f"visit_type must be one of {sorted(self.repo.clinic.visit_types)}.")
        if provider and self.repo.clinic.provider(provider) is None:
            return _err("unknown_provider",
                        f"provider must be one of {[p.id for p in self.repo.clinic.providers]}.")
        if part_of_day not in ("any", "morning", "afternoon"):
            return _err("invalid_part_of_day", "part_of_day must be any, morning or afternoon.")
        start, e1 = _parse_date(date_from, "date_from")
        end, e2 = _parse_date(date_to, "date_to")
        if e1 or e2 or start is None or end is None:
            return e1 or e2 or _err("invalid_date", "date_from and date_to are required.")
        nb = self.now
        if not_before:
            try:
                nb = datetime.fromisoformat(not_before).replace(tzinfo=None)
            except ValueError:
                return _err("invalid_datetime", "not_before must be ISO format.")
        limit = max(1, min(int(limit), 20))
        slots = scheduling.find_free_slots(
            self.repo, visit_type=visit_type, date_from=start, date_to=end, today=self.today,
            provider=provider, part_of_day=part_of_day, not_before=nb, limit=limit,  # type: ignore[arg-type]
        )
        unavailable = self._unavailability_notes(start, end, provider)
        return {"ok": True, "slots": [s.to_dict() for s in slots], "count": len(slots),
                "notes": unavailable}

    def book_appointment(
        self, patient_id: str, verification_token: str, provider: str, date: str, start: str,
        visit_type: str, message_id: str,
    ) -> dict:
        if error := self._require_grant(patient_id, verification_token):
            return error
        day, e = _parse_date(date, "date")
        if e or day is None:
            return e or _err("invalid_date", "date is required.")
        problems = scheduling.booking_violations(
            self.repo, provider=provider, day=day, start=start, visit_type=visit_type,
            today=self.today, not_before=self.now,
        )
        if problems:
            return _err("slot_not_bookable",
                        "This slot cannot be booked. Use find_free_slots to offer alternatives.",
                        violations=problems)
        appt = scheduling.make_appointment(
            self.repo, patient_id=patient_id, provider=provider, day=day, start=start,
            visit_type=visit_type,
        )
        self.repo.add_appointment(appt)
        self._record_change("booked", appt.id, message_id)
        return {"ok": True, "appointment": self._appt_view(appt)}

    def reschedule_appointment(
        self, appointment_id: str, patient_id: str, verification_token: str, new_date: str,
        new_start: str, message_id: str, new_provider: str | None = None,
    ) -> dict:
        if error := self._require_grant(patient_id, verification_token):
            return error
        appt = self.repo.appointment(appointment_id)
        if appt is None or appt.patient_id != patient_id or appt.status != "booked":
            return _err("appointment_not_found",
                        f"No booked appointment {appointment_id} for patient {patient_id}.")
        day, e = _parse_date(new_date, "new_date")
        if e or day is None:
            return e or _err("invalid_date", "new_date is required.")
        provider = new_provider or appt.provider
        problems = scheduling.booking_violations(
            self.repo, provider=provider, day=day, start=new_start, visit_type=appt.visit_type,
            today=self.today, not_before=self.now, ignore_appointment_id=appt.id,
        )
        if problems:
            return _err("slot_not_bookable",
                        "The new time cannot be booked; the original appointment is unchanged.",
                        violations=problems)
        # Book the new slot first, then cancel the old one, so a failure never leaves the
        # patient with no appointment at all.
        new_appt = scheduling.make_appointment(
            self.repo, patient_id=patient_id, provider=provider, day=day, start=new_start,
            visit_type=appt.visit_type,
        )
        self.repo.add_appointment(new_appt)
        appt.status = "cancelled"
        self._record_change("rescheduled", new_appt.id, message_id, replaces=appt.id)
        return {"ok": True, "previous": self._appt_view(appt), "appointment": self._appt_view(new_appt)}

    def cancel_appointment(
        self, appointment_id: str, patient_id: str, verification_token: str, message_id: str
    ) -> dict:
        if error := self._require_grant(patient_id, verification_token):
            return error
        appt = self.repo.appointment(appointment_id)
        if appt is None or appt.patient_id != patient_id:
            return _err("appointment_not_found",
                        f"No appointment {appointment_id} for patient {patient_id}.")
        if appt.status == "cancelled":
            return {"ok": True, "appointment": self._appt_view(appt), "already_cancelled": True}
        appt.status = "cancelled"
        self._record_change("cancelled", appt.id, message_id)
        return {"ok": True, "appointment": self._appt_view(appt), "already_cancelled": False}

    # ------------------------------------------------------------------ clinic info

    def get_clinic_info(self) -> dict:
        c = self.repo.clinic
        return {
            "ok": True,
            "clinic_name": c.clinic_name,
            "today": self.today.isoformat(),
            "today_weekday": scheduling.weekday_name(self.today),
            "timezone": c.timezone,
            "hours": {"days": c.hours.days, "open": c.hours.open, "close": c.hours.close,
                      "lunch": list(c.hours.lunch)},
            "holidays": [d.isoformat() for d in c.holidays],
            "providers": [
                {"id": p.id, "name": p.name, "role": p.role, "languages": p.languages,
                 "leave": [[s.isoformat(), e.isoformat()] for s, e in p.leave]}
                for p in c.providers
            ],
            "visit_type_minutes": c.visit_types,
            "booking_rules": c.booking_rules,
            "schedule_known_until": scheduling.schedule_window_end(self.repo).isoformat(),
        }

    def check_clinic_open(self, date: str) -> dict:
        day, e = _parse_date(date, "date")
        if e or day is None:
            return e or _err("invalid_date", "date is required.")
        c = self.repo.clinic
        if scheduling.is_holiday(c, day):
            reason = "holiday"
        elif scheduling.weekday_name(day) not in c.hours.days:
            reason = "weekend"
        else:
            reason = None
        return {
            "ok": True, "date": day.isoformat(), "weekday": scheduling.weekday_name(day),
            "open": reason is None, "closed_reason": reason,
            "hours": None if reason else {"open": c.hours.open, "close": c.hours.close,
                                          "lunch": list(c.hours.lunch)},
            "providers_on_leave": [p.id for p in c.providers
                                   if scheduling.provider_on_leave(c, p.id, day)],
        }

    # ------------------------------------------------------------------ handoff to humans

    def route_to_queue(
        self, message_id: str, queue: str, reason: str, priority: str = "routine",
        patient_id: str | None = None,
    ) -> dict:
        if queue not in self.repo.clinic.routing_queues:
            return _err("unknown_queue", f"queue must be one of {self.repo.clinic.routing_queues}.")
        if priority not in PRIORITIES:
            return _err("invalid_priority", f"priority must be one of {list(PRIORITIES)}.")
        for t in self.log.queue_tickets:  # duplicate protection
            if t["message_id"] == message_id and t["queue"] == queue:
                return {"ok": True, "ticket": t, "duplicate": True}
        ticket = {
            "ticket_id": f"T{len(self.log.queue_tickets) + 1:03d}",
            "message_id": message_id, "queue": queue, "priority": priority,
            "reason": reason, "patient_id": patient_id,
        }
        self.log.queue_tickets.append(ticket)
        return {"ok": True, "ticket": ticket, "duplicate": False}

    def draft_reply(self, message_id: str, text: str, language: str = "English") -> dict:
        if not text or not text.strip():
            return _err("empty_reply", "Reply text must not be empty.")
        draft = {"message_id": message_id, "language": language, "text": text.strip(),
                 "status": "draft_for_staff_review"}
        self.log.reply_drafts = [d for d in self.log.reply_drafts if d["message_id"] != message_id]
        self.log.reply_drafts.append(draft)
        return {"ok": True, "draft": draft}

    def flag_suspicious_instruction(self, message_id: str, excerpt: str, reason: str) -> dict:
        flag = {"message_id": message_id, "excerpt": excerpt[:300], "reason": reason}
        self.log.flags.append(flag)
        return {"ok": True, "flag": flag}

    # ------------------------------------------------------------------ helpers

    def _appt_view(self, a) -> dict:
        provider = self.repo.clinic.provider(a.provider)
        return {
            "appointment_id": a.id, "patient_id": a.patient_id, "provider": a.provider,
            "provider_name": provider.name if provider else a.provider,
            "date": a.date.isoformat(), "weekday": scheduling.weekday_name(a.date),
            "start": a.start, "end": a.end, "visit_type": a.visit_type, "status": a.status,
        }

    def _record_change(self, kind: str, appointment_id: str, message_id: str, **extra) -> None:
        self.log.appointment_changes.append(
            {"kind": kind, "appointment_id": appointment_id, "message_id": message_id, **extra}
        )

    def _unavailability_notes(self, start: date, end: date, provider: str | None) -> list[str]:
        c = self.repo.clinic
        notes = [f"{d.isoformat()} is a clinic holiday" for d in c.holidays if start <= d <= end]
        for p in c.providers:
            if provider and p.id != provider:
                continue
            for ls, le in p.leave:
                if ls <= end and start <= le:
                    notes.append(f"{p.name} ({p.id}) is on leave {ls.isoformat()} to {le.isoformat()}")
        window_end = scheduling.schedule_window_end(self.repo)
        if end > window_end:
            notes.append(f"Schedule is only known until {window_end.isoformat()}")
        return notes


def _age(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
