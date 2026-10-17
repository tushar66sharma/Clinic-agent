"""Booking rules and free-slot search, implementing `hours` and `booking_rules` in clinic.json.

Rules enforced:
- Open Mon-Fri 09:00-17:00, closed on holidays.
- Appointments start on the hour or at :20 / :40.
- No bookings during lunch (12:00-13:00), on holidays, or on provider leave.
- A provider cannot have overlapping appointments.
- Appointment length comes from `visit_types` (e.g. annual_physical = 40 minutes).
- Nothing in the past, and nothing beyond the last date of the known schedule
  (we cannot rule out double-booking on days the schedule does not cover).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from .models import Appointment, Clinic
from .repository import ClinicRepository

SLOT_STEP_MINUTES = 20  # starts allowed on :00, :20, :40
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

PartOfDay = Literal["any", "morning", "afternoon"]


def parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def to_minutes(value: str | time) -> int:
    t = parse_hhmm(value) if isinstance(value, str) else value
    return t.hour * 60 + t.minute


def fmt_minutes(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def weekday_name(d: date) -> str:
    return WEEKDAY_NAMES[d.weekday()]


def is_holiday(clinic: Clinic, d: date) -> bool:
    return d in clinic.holidays


def is_open_day(clinic: Clinic, d: date) -> bool:
    return weekday_name(d) in clinic.hours.days and not is_holiday(clinic, d)


def provider_on_leave(clinic: Clinic, provider_id: str, d: date) -> bool:
    provider = clinic.provider(provider_id)
    return bool(provider) and any(start <= d <= end for start, end in provider.leave)


def schedule_window_end(repo: ClinicRepository) -> date:
    return max(a.date for a in repo.appointments)


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def booking_violations(
    repo: ClinicRepository,
    *,
    provider: str,
    day: date,
    start: str,
    visit_type: str,
    today: date,
    not_before: datetime | None = None,
    ignore_appointment_id: str | None = None,
) -> list[str]:
    """Return every rule the proposed booking breaks. An empty list means it is allowed."""
    clinic = repo.clinic
    problems: list[str] = []

    if clinic.provider(provider) is None:
        problems.append("unknown_provider")
    if visit_type not in clinic.visit_types:
        problems.append("unknown_visit_type")
    try:
        start_min = to_minutes(start)
    except ValueError:
        return problems + ["invalid_time_format"]
    if problems:
        return problems

    end_min = start_min + clinic.visit_types[visit_type]
    open_min, close_min = to_minutes(clinic.hours.open), to_minutes(clinic.hours.close)
    lunch_start, lunch_end = (to_minutes(t) for t in clinic.hours.lunch)

    if day < today or (not_before and datetime.combine(day, parse_hhmm(start)) < not_before):
        problems.append("in_the_past")
    if day > schedule_window_end(repo):
        problems.append("outside_known_schedule")
    if is_holiday(clinic, day):
        problems.append("clinic_holiday")
    elif weekday_name(day) not in clinic.hours.days:
        problems.append("clinic_closed_that_day")
    if provider_on_leave(clinic, provider, day):
        problems.append("provider_on_leave")
    if start_min % SLOT_STEP_MINUTES != 0:
        problems.append("start_not_on_20_minute_grid")
    if start_min < open_min or end_min > close_min:
        problems.append("outside_opening_hours")
    if _overlaps(start_min, end_min, lunch_start, lunch_end):
        problems.append("overlaps_lunch")
    for appt in repo.booked_appointments():
        if appt.id == ignore_appointment_id or appt.provider != provider or appt.date != day:
            continue
        if _overlaps(start_min, end_min, to_minutes(appt.start), to_minutes(appt.end)):
            problems.append("provider_already_booked")
            break
    return problems


@dataclass
class Slot:
    provider: str
    provider_name: str
    date: str
    weekday: str
    start: str
    end: str
    visit_type: str

    def to_dict(self) -> dict:
        return asdict(self)


def find_free_slots(
    repo: ClinicRepository,
    *,
    visit_type: str,
    date_from: date,
    date_to: date,
    today: date,
    provider: str | None = None,
    part_of_day: PartOfDay = "any",
    not_before: datetime | None = None,
    limit: int = 10,
    ignore_appointment_id: str | None = None,
) -> list[Slot]:
    """List bookable slots in date order. Every slot returned passes `booking_violations`."""
    clinic = repo.clinic
    if visit_type not in clinic.visit_types:
        return []
    providers = [clinic.provider(provider)] if provider else list(clinic.providers)
    providers = [p for p in providers if p is not None]
    duration = clinic.visit_types[visit_type]
    open_min, close_min = to_minutes(clinic.hours.open), to_minutes(clinic.hours.close)
    noon = to_minutes(clinic.hours.lunch[0])
    lunch_end = to_minutes(clinic.hours.lunch[1])

    slots: list[Slot] = []
    day = max(date_from, today)
    last = min(date_to, schedule_window_end(repo))
    while day <= last and len(slots) < limit:
        if is_open_day(clinic, day):
            for start_min in range(open_min, close_min - duration + 1, SLOT_STEP_MINUTES):
                if part_of_day == "morning" and start_min >= noon:
                    continue
                if part_of_day == "afternoon" and start_min < lunch_end:
                    continue
                for p in providers:
                    start = fmt_minutes(start_min)
                    if booking_violations(
                        repo, provider=p.id, day=day, start=start, visit_type=visit_type,
                        today=today, not_before=not_before,
                        ignore_appointment_id=ignore_appointment_id,
                    ):
                        continue
                    slots.append(Slot(
                        provider=p.id, provider_name=p.name, date=day.isoformat(),
                        weekday=weekday_name(day), start=start,
                        end=fmt_minutes(start_min + duration), visit_type=visit_type,
                    ))
                    if len(slots) >= limit:
                        return slots
        day += timedelta(days=1)
    return slots


def make_appointment(
    repo: ClinicRepository, *, patient_id: str, provider: str, day: date, start: str,
    visit_type: str,
) -> Appointment:
    duration = repo.clinic.visit_types[visit_type]
    return Appointment(
        id=repo.new_appointment_id(), patient_id=patient_id, provider=provider, date=day,
        start=start, end=fmt_minutes(to_minutes(start) + duration), visit_type=visit_type,
        status="booked",
    )
