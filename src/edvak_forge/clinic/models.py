"""Typed models for the clinic data files in `data/`.

Validating the files on load means a malformed record fails loudly at startup instead of
producing a wrong refill or booking decision later.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class Caregiver(BaseModel):
    name: str
    relationship: str
    phone: str | None = None
    email: str | None = None


class Patient(BaseModel):
    id: str
    name: str
    dob: date
    phone: str
    email: str
    primary_provider: str
    last_visit: date
    allergies: list[str] = Field(default_factory=list)
    preferred_language: str = "English"
    authorised_caregiver: Caregiver | None = None


class Medication(BaseModel):
    patient_id: str
    medication: str
    controlled_schedule: str | None = None
    days_supply: int
    last_filled: date
    refills_remaining: int
    prescriber: str


class Appointment(BaseModel):
    id: str
    patient_id: str
    provider: str
    date: date
    start: str  # "HH:MM"
    end: str  # "HH:MM"
    visit_type: str
    status: str  # "booked" | "cancelled"


class Provider(BaseModel):
    id: str
    name: str
    role: str
    languages: list[str] = Field(default_factory=list)
    leave: list[tuple[date, date]] = Field(default_factory=list)


class Hours(BaseModel):
    days: list[str]
    open: str
    close: str
    lunch: tuple[str, str]


class RefillPolicy(BaseModel):
    agent_may: str
    eligible_if: list[str]
    controlled_substances: str
    not_seen_in_12_months: str
    zero_refills_remaining: str
    too_early: str


class Clinic(BaseModel):
    clinic_name: str
    today: date
    timezone: str
    hours: Hours
    holidays: list[date]
    providers: list[Provider]
    visit_types: dict[str, int]
    booking_rules: list[str]
    refill_policy: RefillPolicy
    safety_policy: str
    privacy_policy: str
    routing_queues: list[str]

    def provider(self, provider_id: str) -> Provider | None:
        return next((p for p in self.providers if p.id == provider_id), None)
