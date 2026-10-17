"""Refill policy, one test per refill case in labels_sample.json."""

from datetime import date

import pytest

from edvak_forge.clinic.refills import check_refill, match_medications, months_ago

TODAY = date(2026, 11, 9)


def decide(repo, patient_id, query):
    meds = match_medications(repo.medications_for(patient_id), query)
    assert len(meds) == 1, f"{query!r} matched {[m.medication for m in meds]}"
    return check_refill(meds[0], repo.patient(patient_id), TODAY)


@pytest.mark.parametrize(
    "message, patient_id, query, status, actions",
    [
        ("M001", "P002", "lisinopril", "eligible", ["prepare_refill_for_approval"]),
        ("M004", "P004", "metformin", "not_seen_12_months",
         ["refill_needs_visit", "offer_appointment", "route_to_provider"]),
        ("M005", "P006", "Xanax", "controlled_substance", ["route_to_provider"]),
        ("M006", "P005", "sertraline", "eligible", ["prepare_refill_for_approval"]),
        ("M009", "P012", "levothyroxine", "eligible", ["prepare_refill_for_approval"]),
        ("M012", "P014", "zolpidem", "controlled_substance", ["route_to_provider"]),
        ("M013", "P015", "omeprazole", "too_early", ["refill_too_early"]),
        ("M018", "P022", "insulin", "eligible", ["prepare_refill_for_approval"]),
        ("M019", "P021", "oxycodone", "controlled_substance", ["route_to_provider"]),
        ("M020", "P001", "metformina", "eligible", ["prepare_refill_for_approval"]),
        ("M021", "P008", "Amlodipine", "zero_refills", ["route_to_provider"]),
        ("M025", "P024", "atorvastatin", "eligible", ["prepare_refill_for_approval"]),
        ("M026", "P016", "escitalopram", "not_seen_12_months",
         ["refill_needs_visit", "offer_appointment", "route_to_provider"]),
        ("M036", "P017", "donepezil", "too_early", ["refill_too_early"]),
    ],
)
def test_sample_refill_decisions(repo, message, patient_id, query, status, actions):
    d = decide(repo, patient_id, query)
    assert d.status == status, f"{message}: {d.explanation}"
    assert d.recommended_actions == actions
    assert d.eligible == (status == "eligible")


def test_m013_earliest_request_date_is_17_nov(repo):
    d = decide(repo, "P015", "omeprazole")
    assert d.run_out_date == "2026-11-24"
    assert d.earliest_request_date == "2026-11-17"


def test_m036_supply_lasts_to_28_nov(repo):
    assert decide(repo, "P017", "donepezil").run_out_date == "2026-11-28"


def test_m005_controlled_wins_over_other_failures(repo):
    d = decide(repo, "P006", "alprazolam")
    assert d.status == "controlled_substance"
    assert "zero_refills" in d.failed_rules  # still reported


def test_exactly_seven_days_before_run_out_is_eligible(repo):
    # P002 lisinopril runs out 2026-11-13, so the window opens 2026-11-06.
    med = match_medications(repo.medications_for("P002"), "lisinopril")[0]
    assert check_refill(med, repo.patient("P002"), date(2026, 11, 6)).eligible
    assert not check_refill(med, repo.patient("P002"), date(2026, 11, 5)).eligible


def test_brand_names_and_spanish_names_match():
    from edvak_forge.clinic.refills import MEDICATION_ALIASES
    assert MEDICATION_ALIASES["xanax"] == "alprazolam"
    assert MEDICATION_ALIASES["metformina"] == "metformin"


def test_unknown_medication_matches_nothing(repo):
    assert match_medications(repo.medications_for("P002"), "ibuprofen") == []


def test_empty_query_returns_all(repo):
    assert len(match_medications(repo.medications_for("P002"), "")) == 2


def test_months_ago_handles_leap_day():
    assert months_ago(date(2028, 2, 29), 12) == date(2027, 2, 28)
    assert months_ago(TODAY, 12) == date(2025, 11, 9)
