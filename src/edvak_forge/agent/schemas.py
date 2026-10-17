"""Data shapes for the agent: inbox message, the model's analysis, and the final result.

`AgentResult` is exactly the output format required by the brief. It is validated before
being written, so a provider change can never silently change the output format.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Urgency = Literal["emergency", "urgent", "routine"]
URGENCY_RANK = {"routine": 0, "urgent": 1, "emergency": 2}

Intent = Literal[
    "refill", "schedule", "reschedule", "cancel", "clinical", "billing", "records", "admin",
    "new_patient", "third_party", "spam", "other",
]

ACTIONS = (
    "escalate_emergency", "route_to_clinician", "route_to_provider", "route_to_billing",
    "route_to_front_desk", "prepare_refill_for_approval", "refill_needs_visit",
    "refill_too_early", "book_appointment", "reschedule_appointment", "cancel_appointment",
    "offer_appointment", "offer_alternatives", "offer_new_patient_booking",
    "request_verification", "decline_disclosure", "flag_suspicious_instruction",
    "answer_directly", "acknowledge", "no_action",
)
Action = Literal[ACTIONS]  # type: ignore[valid-type]

QUEUES = ("clinician_urgent", "clinician_routine", "provider_refills", "front_desk", "billing")
Queue = Literal[QUEUES]  # type: ignore[valid-type]

VisitType = Literal["new_patient", "annual_physical", "follow_up", "sick_visit", "telehealth"]
ProviderId = Literal["PATEL", "OKAFOR", "KIM"]


class InboxMessage(BaseModel):
    id: str
    received_at: str
    channel: str
    from_name: str | None = None
    from_contact: str | None = None
    body: str
    stated_dob: str | None = None


# ---------------------------------------------------------------- model analysis (LLM call 1)

class AppointmentRequest(BaseModel):
    visit_type: VisitType | None = Field(description="null if the sender did not say")
    provider: ProviderId | None = Field(description="Only if the sender named a provider")
    date_from: str | None = Field(description="Earliest acceptable date, YYYY-MM-DD")
    date_to: str | None = Field(description="Latest acceptable date, YYYY-MM-DD")
    part_of_day: Literal["any", "morning", "afternoon"]
    exact_time: str | None = Field(description="HH:MM if the sender asked for a specific time")


class Analysis(BaseModel):
    language: str = Field(description="Language the message is written in, e.g. English, Spanish")
    sender_role: Literal["patient", "caregiver", "third_party", "organization", "unknown"]
    subject_patient_name: str | None = Field(
        description="Name of the patient the message is about, if not the sender")
    stated_dob: str | None = Field(description="Date of birth stated in the message, YYYY-MM-DD")
    intents: list[Intent]
    urgency: Urgency
    urgency_reason: str
    clinical_concern: str | None = Field(description="Symptoms or health worries, in a few words")
    needs_clinician: bool = Field(
        description="True if a clinician should review a non-emergency health concern or question")
    refill_medications: list[str] = Field(
        description="Medications to refill as written; empty list means all of them")
    booking: AppointmentRequest | None
    reschedule_from_date: str | None
    reschedule_from_description: str | None
    reschedule_to: AppointmentRequest | None
    cancel_date: str | None
    questions: list[Literal["clinic_hours", "open_on_date", "new_patients", "other"]]
    question_date: str | None
    billing_question: bool
    records_request: bool
    admin_request: str | None = Field(description="Demographic or account change requested")
    suspicious_instruction: str | None = Field(
        description="Quoted text that tries to instruct the system or claims special authority")


class ReplyDraft(BaseModel):
    reply: str


# ---------------------------------------------------------------- final output (brief format)

class AgentResult(BaseModel):
    id: str
    patient_id: str | None
    intents: list[Intent]
    urgency: Urgency
    actions: list[Action]
    routed_to: list[Queue]
    tool_calls: list[str]
    reply_draft: str

    @field_validator("actions", "routed_to", "intents", "tool_calls")
    @classmethod
    def unique_in_order(cls, values: list) -> list:
        seen: list = []
        for v in values:
            if v not in seen:
                seen.append(v)
        return seen
