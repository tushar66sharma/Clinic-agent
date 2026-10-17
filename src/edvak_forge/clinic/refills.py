"""Refill eligibility, implementing `refill_policy` in clinic.json exactly.

Eligible only if ALL hold:
  1. the medication is on the patient's active list
  2. it is not a controlled substance
  3. the patient was seen within the last 12 months
  4. refills_remaining > 0
  5. today is no more than 7 days before the supply runs out (last_filled + days_supply)

When several rules fail, the status reports the most serious one, in this order:
controlled > not_seen_12_months > zero_refills > too_early. All failures are still listed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Literal

from .models import Medication, Patient

REFILL_WINDOW_DAYS = 7  # "no more than 7 days before the current supply runs out"
LOOKBACK_MONTHS = 12  # "seen within the last 12 months"

RefillStatus = Literal[
    "eligible", "controlled_substance", "not_seen_12_months", "zero_refills", "too_early"
]

# Brand names and Spanish spellings patients actually write -> generic name on file.
MEDICATION_ALIASES: dict[str, str] = {
    "xanax": "alprazolam",
    "ambien": "zolpidem",
    "adderall": "amphetamine",
    "percocet": "oxycodone",
    "oxycontin": "oxycodone",
    "roxicodone": "oxycodone",
    "lipitor": "atorvastatin",
    "zestril": "lisinopril",
    "prinivil": "lisinopril",
    "zestoretic": "lisinopril",
    "synthroid": "levothyroxine",
    "levoxyl": "levothyroxine",
    "prilosec": "omeprazole",
    "zoloft": "sertraline",
    "lexapro": "escitalopram",
    "norvasc": "amlodipine",
    "glucophage": "metformin",
    "coumadin": "warfarin",
    "jantoven": "warfarin",
    "aricept": "donepezil",
    "lantus": "insulin",
    "basaglar": "insulin",
    "zyrtec": "cetirizine",
    "ventolin": "albuterol",
    "proair": "albuterol",
    "inhaler": "albuterol",
    # Spanish
    "metformina": "metformin",
    "sertralina": "sertraline",
    "lisinoprilo": "lisinopril",
    "omeprazol": "omeprazole",
    "atorvastatina": "atorvastatin",
    "levotiroxina": "levothyroxine",
    "insulina": "insulin",
    "warfarina": "warfarin",
    "amlodipino": "amlodipine",
    "escitalopram": "escitalopram",
    "donepezilo": "donepezil",
    "inhalador": "albuterol",
}


def _words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.findall(r"[a-z]+", text)


def match_medications(medications: list[Medication], query: str | None) -> list[Medication]:
    """Find the patient's medications named in `query` (generic, brand or Spanish name).

    An empty query returns every active medication.
    """
    if not query or not query.strip():
        return list(medications)
    wanted = {MEDICATION_ALIASES.get(w, w) for w in _words(query)}
    wanted = {w for w in wanted if len(w) >= 4}
    found = []
    for med in medications:
        med_words = set(_words(med.medication))
        if any(w in med_words or any(m.startswith(w) or w.startswith(m) for m in med_words
                                     if len(m) >= 4) for w in wanted):
            found.append(med)
    return found


def run_out_date(med: Medication) -> date:
    return med.last_filled + timedelta(days=med.days_supply)


def earliest_request_date(med: Medication) -> date:
    return run_out_date(med) - timedelta(days=REFILL_WINDOW_DAYS)


def months_ago(today: date, months: int) -> date:
    year, month = divmod(today.month - 1 - months, 12)
    year += today.year
    month += 1
    day = today.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:  # e.g. 29 Feb in a non-leap year
            day -= 1


@dataclass
class RefillDecision:
    medication: str
    status: RefillStatus
    eligible: bool
    failed_rules: list[str]
    run_out_date: str
    earliest_request_date: str
    refills_remaining: int
    controlled_schedule: str | None
    prescriber: str
    recommended_actions: list[str] = field(default_factory=list)
    recommended_queue: str | None = None
    explanation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def check_refill(med: Medication, patient: Patient, today: date) -> RefillDecision:
    failed: list[str] = []
    if med.controlled_schedule:
        failed.append("controlled_substance")
    if patient.last_visit < months_ago(today, LOOKBACK_MONTHS):
        failed.append("not_seen_12_months")
    if med.refills_remaining <= 0:
        failed.append("zero_refills")
    if today < earliest_request_date(med):
        failed.append("too_early")

    runout = run_out_date(med)
    earliest = earliest_request_date(med)
    base = dict(
        medication=med.medication,
        failed_rules=failed,
        run_out_date=runout.isoformat(),
        earliest_request_date=earliest.isoformat(),
        refills_remaining=med.refills_remaining,
        controlled_schedule=med.controlled_schedule,
        prescriber=med.prescriber,
    )

    if "controlled_substance" in failed:
        return RefillDecision(
            **base, status="controlled_substance", eligible=False,
            recommended_actions=["route_to_provider"], recommended_queue="provider_refills",
            explanation=f"{med.medication} is a controlled substance ({med.controlled_schedule}). "
                        "The agent never prepares these; route to the prescribing provider.",
        )
    if "not_seen_12_months" in failed:
        return RefillDecision(
            **base, status="not_seen_12_months", eligible=False,
            recommended_actions=["refill_needs_visit", "offer_appointment", "route_to_provider"],
            recommended_queue="provider_refills",
            explanation=f"Last visit {patient.last_visit.isoformat()} is more than 12 months ago. "
                        "Do not prepare the refill; offer an appointment and route to the provider.",
        )
    if "zero_refills" in failed:
        return RefillDecision(
            **base, status="zero_refills", eligible=False,
            recommended_actions=["route_to_provider"], recommended_queue="provider_refills",
            explanation="No refills remaining; the provider must write a new prescription.",
        )
    if "too_early" in failed:
        return RefillDecision(
            **base, status="too_early", eligible=False,
            recommended_actions=["refill_too_early"], recommended_queue=None,
            explanation=f"Supply lasts until {runout.isoformat()}. The earliest date the request "
                        f"can be prepared is {earliest.isoformat()}.",
        )
    return RefillDecision(
        **base, status="eligible", eligible=True,
        recommended_actions=["prepare_refill_for_approval"], recommended_queue="provider_refills",
        explanation="Eligible. Prepare a refill request for provider approval "
                    "(the agent never approves or sends a prescription).",
    )
