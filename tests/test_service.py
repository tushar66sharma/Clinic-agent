"""ClinicService: verification gates, refusals, duplicates and state changes."""

from tests.conftest import verified_token

# --- privacy gate -------------------------------------------------------------------------

def test_health_tools_refuse_without_token(service):
    for call in (
        lambda: service.get_medications("P002", ""),
        lambda: service.check_refill_eligibility("P002", "bogus", "lisinopril"),
        lambda: service.list_appointments("P013", "bogus"),
        lambda: service.get_patient_profile("P002", ""),
    ):
        result = call()
        assert result["ok"] is False
        assert result["error"]["code"] == "verification_required"


def test_token_for_one_patient_does_not_open_another(service):
    token = verified_token(service, "P002")
    assert service.get_medications("P001", token)["error"]["code"] == "verification_required"


def test_unverified_sender_gets_no_token(service):
    r = service.verify_sender("P013", "Mike", "555-0888")
    assert r["verified"] is False and "verification_token" not in r


# --- refills ------------------------------------------------------------------------------

def test_prepare_refill_for_eligible_medication(service):
    token = verified_token(service, "P002")
    r = service.prepare_refill_request("P002", token, "lisinopril", "M001")
    assert r["ok"] and r["refill_request"]["status"] == "pending_provider_approval"


def test_prepare_refill_refuses_controlled_substance(service):
    token = verified_token(service, "P006")
    r = service.prepare_refill_request("P006", token, "Xanax", "M005")
    assert r["ok"] is False and r["error"]["code"] == "refill_not_eligible"
    assert service.log.refill_requests == []


def test_prepare_refill_refuses_too_early(service):
    token = verified_token(service, "P015")
    r = service.prepare_refill_request("P015", token, "omeprazole", "M013")
    assert r["ok"] is False and "too_early" in r["error"]["message"]


def test_duplicate_refill_request_is_not_created_twice(service):
    token = verified_token(service, "P002")
    service.prepare_refill_request("P002", token, "lisinopril", "M001")
    again = service.prepare_refill_request("P002", token, "lisinopril", "M001")
    assert again["duplicate"] is True
    assert len(service.log.refill_requests) == 1


def test_medication_not_on_list(service):
    token = verified_token(service, "P002")
    r = service.check_refill_eligibility("P002", token, "ibuprofen")
    assert r["not_on_active_list"] is True
    assert r["recommended_actions"] == ["route_to_provider"]


# --- appointments -------------------------------------------------------------------------

def test_m002_reschedule_wednesday_to_friday_afternoon(service):
    token = verified_token(service, "P007")
    appts = service.list_appointments("P007", token, "2026-11-11", "2026-11-11")["appointments"]
    assert [a["appointment_id"] for a in appts] == ["A035"]
    slot = service.find_free_slots("follow_up", "2026-11-13", "2026-11-13", "KIM",
                                   "afternoon")["slots"][0]
    r = service.reschedule_appointment("A035", "P007", token, slot["date"], slot["start"], "M002")
    assert r["ok"], r
    assert r["previous"]["status"] == "cancelled"
    assert r["appointment"]["date"] == "2026-11-13"


def test_failed_reschedule_keeps_original(service):
    token = verified_token(service, "P007")
    r = service.reschedule_appointment("A035", "P007", token, "2026-11-27", "10:00", "M002")
    assert r["ok"] is False and "clinic_holiday" in r["error"]["violations"]
    assert service.repo.appointment("A035").status == "booked"


def test_m029_booking_taken_slot_fails_with_reason(service):
    token = verified_token(service, "P002")
    r = service.book_appointment("P002", token, "OKAFOR", "2026-11-12", "14:00", "follow_up",
                                 "M029")
    assert r["ok"] is False
    assert "provider_already_booked" in r["error"]["violations"]


def test_booking_then_same_slot_is_no_longer_offered(service):
    token = verified_token(service, "P013")
    slot = service.find_free_slots("follow_up", "2026-11-17", "2026-11-17", "PATEL",
                                   "morning")["slots"][0]
    assert service.book_appointment("P013", token, "PATEL", slot["date"], slot["start"],
                                    "follow_up", "M010")["ok"]
    again = service.find_free_slots("follow_up", "2026-11-17", "2026-11-17", "PATEL", "morning")
    assert slot["start"] not in [s["start"] for s in again["slots"]]


def test_clock_hides_slots_that_already_passed(service):
    service.set_clock("2026-11-09T14:00:00-06:00")
    slots = service.find_free_slots("sick_visit", "2026-11-09", "2026-11-09")["slots"]
    assert all(s["start"] >= "14:00" for s in slots)


def test_m022_cancel_and_cancel_again_is_idempotent(service):
    token = verified_token(service, "P011")
    assert service.cancel_appointment("A017", "P011", token, "M022")["already_cancelled"] is False
    assert service.cancel_appointment("A017", "P011", token, "M022")["already_cancelled"] is True


def test_cannot_cancel_someone_elses_appointment(service):
    token = verified_token(service, "P011")
    r = service.cancel_appointment("A035", "P011", token, "M022")  # A035 belongs to P007
    assert r["error"]["code"] == "appointment_not_found"


def test_slot_search_explains_leave_and_holidays(service):
    notes = service.find_free_slots("follow_up", "2026-11-16", "2026-11-27", "OKAFOR")["notes"]
    assert any("leave" in n for n in notes)
    assert any("2026-11-27" in n for n in notes)


# --- clinic info and handoff --------------------------------------------------------------

def test_m023_day_after_thanksgiving_is_closed(service):
    r = service.check_clinic_open("2026-11-27")
    assert r["open"] is False and r["closed_reason"] == "holiday"


def test_route_rejects_unknown_queue_and_dedupes(service):
    assert service.route_to_queue("M008", "accounts", "x")["error"]["code"] == "unknown_queue"
    service.route_to_queue("M008", "billing", "balance question")
    assert service.route_to_queue("M008", "billing", "again")["duplicate"] is True
    assert len(service.log.queue_tickets) == 1


def test_draft_reply_replaces_previous_draft(service):
    service.draft_reply("M037", "first")
    service.draft_reply("M037", "second")
    assert [d["text"] for d in service.log.reply_drafts] == ["second"]


def test_invalid_dates_are_rejected_not_raised(service):
    assert service.check_clinic_open("next friday")["error"]["code"] == "invalid_date"
