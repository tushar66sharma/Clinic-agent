"""Booking rules and slot search, including every scheduling trap in the sample labels."""

from datetime import date, datetime

from edvak_forge.clinic.scheduling import booking_violations, find_free_slots

TODAY = date(2026, 11, 9)


def violations(repo, provider, day, start, visit_type="follow_up", **kw):
    return booking_violations(repo, provider=provider, day=day, start=start,
                              visit_type=visit_type, today=TODAY, **kw)


# --- individual rules ---------------------------------------------------------------------

def test_valid_slot_has_no_violations(repo):
    slots = find_free_slots(repo, visit_type="follow_up", date_from=TODAY, date_to=TODAY,
                            today=TODAY, limit=1)
    s = slots[0]
    assert violations(repo, s.provider, date.fromisoformat(s.date), s.start) == []


def test_m029_thursday_2pm_with_okafor_is_already_booked(repo):
    assert "provider_already_booked" in violations(repo, "OKAFOR", date(2026, 11, 12), "14:00")


def test_m028_okafor_on_leave_18_nov(repo):
    assert "provider_on_leave" in violations(repo, "OKAFOR", date(2026, 11, 18), "10:00")


def test_holiday_day_after_thanksgiving(repo):
    assert "clinic_holiday" in violations(repo, "PATEL", date(2026, 11, 27), "10:00")


def test_weekend_is_closed(repo):
    assert "clinic_closed_that_day" in violations(repo, "PATEL", date(2026, 11, 14), "10:00")


def test_lunch_and_lunch_overlap(repo):
    assert "overlaps_lunch" in violations(repo, "KIM", date(2026, 11, 13), "12:00")
    # A 40-minute physical at 11:40 would run into lunch.
    assert "overlaps_lunch" in violations(repo, "KIM", date(2026, 11, 13), "11:40",
                                          "annual_physical")


def test_start_must_be_on_20_minute_grid(repo):
    assert "start_not_on_20_minute_grid" in violations(repo, "KIM", date(2026, 11, 13), "10:10")


def test_must_end_by_close(repo):
    assert "outside_opening_hours" in violations(repo, "KIM", date(2026, 11, 13), "16:40",
                                                 "annual_physical")


def test_past_dates_and_past_times_today(repo):
    assert "in_the_past" in violations(repo, "KIM", date(2026, 11, 6), "10:00")
    assert "in_the_past" in violations(repo, "KIM", TODAY, "09:00",
                                       not_before=datetime(2026, 11, 9, 10, 30))


def test_beyond_known_schedule_is_refused(repo):
    assert "outside_known_schedule" in violations(repo, "KIM", date(2026, 12, 1), "10:00")


def test_unknown_provider_and_visit_type(repo):
    assert violations(repo, "SMITH", TODAY, "10:00") == ["unknown_provider"]
    assert violations(repo, "KIM", TODAY, "10:00", "massage") == ["unknown_visit_type"]


# --- slot search for the sample scenarios -------------------------------------------------

def test_every_returned_slot_is_bookable(repo):
    slots = find_free_slots(repo, visit_type="annual_physical", date_from=TODAY,
                            date_to=date(2026, 11, 27), today=TODAY, limit=20)
    assert slots
    for s in slots:
        assert violations(repo, s.provider, date.fromisoformat(s.date), s.start,
                          "annual_physical") == []


def test_m002_friday_afternoon_with_kim_exists(repo):
    slots = find_free_slots(repo, visit_type="follow_up", provider="KIM",
                            date_from=date(2026, 11, 13), date_to=date(2026, 11, 13),
                            part_of_day="afternoon", today=TODAY)
    assert slots and all(s.start >= "13:00" for s in slots)


def test_m010_tuesday_17_morning_with_patel(repo):
    slots = find_free_slots(repo, visit_type="follow_up", provider="PATEL",
                            date_from=date(2026, 11, 17), date_to=date(2026, 11, 17),
                            part_of_day="morning", today=TODAY)
    assert slots and all(s.start < "12:00" for s in slots)


def test_m015_sick_visit_with_kim_today_or_tomorrow(repo):
    slots = find_free_slots(repo, visit_type="sick_visit", provider="KIM", date_from=TODAY,
                            date_to=date(2026, 11, 10), today=TODAY,
                            not_before=datetime(2026, 11, 9, 8, 26))
    assert slots


def test_m024_forty_minute_physical_with_kim_this_week(repo):
    slots = find_free_slots(repo, visit_type="annual_physical", provider="KIM", date_from=TODAY,
                            date_to=date(2026, 11, 13), today=TODAY)
    assert slots and all(s.end > s.start for s in slots)


def test_m028_no_okafor_slots_during_leave(repo):
    assert find_free_slots(repo, visit_type="follow_up", provider="OKAFOR",
                           date_from=date(2026, 11, 16), date_to=date(2026, 11, 20),
                           today=TODAY) == []


def test_m034_week_of_23_nov_mornings_skip_holidays(repo):
    slots = find_free_slots(repo, visit_type="annual_physical", provider="PATEL",
                            date_from=date(2026, 11, 23), date_to=date(2026, 11, 27),
                            part_of_day="morning", today=TODAY, limit=20)
    assert slots
    assert not {s.date for s in slots} & {"2026-11-26", "2026-11-27"}
    assert all(s.start < "12:00" for s in slots)
