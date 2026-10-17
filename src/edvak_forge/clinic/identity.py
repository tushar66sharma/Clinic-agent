"""Finding patients and verifying who sent a message.

Privacy policy (clinic.json): health information or appointment details may only be disclosed
when the sender is verified as the patient or an authorised caregiver on file.
Verification = name + date of birth match, OR the message comes from the phone/email on file.

Design calls (documented in docs/security.md):
- A caregiver is verified by messaging from the caregiver phone/email on file, or by giving the
  caregiver's name together with the patient's date of birth.
- A stated date of birth that does NOT match the record blocks verification, even when the
  name matches. A wrong DOB is a red flag, not a near miss.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from .models import Patient

Relationship = Literal["self", "caregiver", "unknown"]


def normalize_name(name: str | None) -> str:
    """Lower-case, strip accents and punctuation, collapse spaces: "O'Brien" -> "obrien"."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]", "", text.lower())
    return " ".join(text.split())


def normalize_phone(phone: str | None) -> str:
    """Keep digits only, and drop a leading US country code: "+1 555-0102" -> "5550102".

    The sample data uses 7-digit numbers, real data uses 10, so "1" + 7 or "1" + 10 digits
    is treated as a country code.
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("1") and len(digits) in (8, 11):
        digits = digits[1:]
    return digits


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def contact_matches(contact: str | None, phone: str | None, email: str | None) -> bool:
    """True when a sender contact (phone or email) equals the given phone or email on file."""
    if not contact:
        return False
    if "@" in contact:
        return bool(email) and normalize_email(contact) == normalize_email(email)
    return bool(phone) and normalize_phone(contact) == normalize_phone(phone)


def names_match(a: str | None, b: str | None) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    return bool(na) and na == nb


@dataclass
class PatientMatch:
    patient_id: str
    name: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def find_patients(
    patients: list[Patient],
    *,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    dob: date | None = None,
) -> list[PatientMatch]:
    """Return patients matching ANY given field, strongest evidence first.

    Matching is exact after normalisation. Fuzzy matching was rejected on purpose: a wrong
    patient match is a privacy incident, a missed match only means asking the sender.
    """
    matches: list[PatientMatch] = []
    for p in patients:
        reasons: list[str] = []
        caregiver = p.authorised_caregiver
        if name and names_match(name, p.name):
            reasons.append("name")
        if name and caregiver and names_match(name, caregiver.name):
            reasons.append("caregiver_name")
        if phone and contact_matches(phone, p.phone, None):
            reasons.append("phone")
        if email and contact_matches(email, None, p.email):
            reasons.append("email")
        if caregiver and phone and contact_matches(phone, caregiver.phone, None):
            reasons.append("caregiver_phone")
        if caregiver and email and contact_matches(email, None, caregiver.email):
            reasons.append("caregiver_email")
        if dob and p.dob == dob:
            reasons.append("dob")
        if reasons:
            matches.append(PatientMatch(patient_id=p.id, name=p.name, reasons=reasons))

    strength = {"phone": 3, "email": 3, "caregiver_phone": 3, "caregiver_email": 3,
                "name": 2, "caregiver_name": 2, "dob": 1}
    matches.sort(key=lambda m: -sum(strength[r] for r in m.reasons))
    return matches


@dataclass
class Verification:
    verified: bool
    relationship: Relationship
    method: str | None  # "contact_on_file" | "name_and_dob" | None
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def verify_sender(
    patient: Patient,
    *,
    from_name: str | None,
    from_contact: str | None,
    stated_dob: date | None = None,
) -> Verification:
    """Decide whether the sender may receive this patient's health or appointment details."""
    caregiver = patient.authorised_caregiver
    is_patient_name = names_match(from_name, patient.name)
    is_caregiver_name = bool(caregiver) and names_match(from_name, caregiver.name)

    # A stated DOB that contradicts the record blocks verification outright.
    if stated_dob is not None and stated_dob != patient.dob:
        return Verification(False, "unknown", None, "stated_dob_does_not_match_record")

    if contact_matches(from_contact, patient.phone, patient.email):
        relationship: Relationship = "caregiver" if is_caregiver_name else "self"
        return Verification(True, relationship, "contact_on_file", "sender_contact_on_file")

    if caregiver and contact_matches(from_contact, caregiver.phone, caregiver.email):
        return Verification(True, "caregiver", "contact_on_file", "caregiver_contact_on_file")

    if stated_dob is not None and (is_patient_name or is_caregiver_name):
        relationship = "self" if is_patient_name else "caregiver"
        return Verification(True, relationship, "name_and_dob", "name_and_dob_match")

    if is_patient_name or is_caregiver_name:
        return Verification(False, "unknown", None, "name_matches_but_contact_not_on_file")
    return Verification(False, "unknown", None, "sender_not_on_file_for_this_patient")
