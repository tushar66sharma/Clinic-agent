"""In-memory clinic data store (see docs/decisions/0003-data-store.md).

Each `ClinicRepository` is an independent copy of the JSON data. Bookings and cancellations
change only that copy, so every run starts from the same schedule and results are repeatable.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Appointment, Clinic, Medication, Patient


class ClinicRepository:
    def __init__(
        self,
        clinic: Clinic,
        patients: list[Patient],
        medications: list[Medication],
        appointments: list[Appointment],
    ) -> None:
        self.clinic = clinic
        self.patients = patients
        self.medications = medications
        self.appointments = appointments
        self._next_appointment_number = self._max_appointment_number() + 1

    @classmethod
    def load(cls, data_dir: Path) -> ClinicRepository:
        def read(name: str):
            path = data_dir / name
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise FileNotFoundError(f"Clinic data file missing: {path}") from exc

        return cls(
            clinic=Clinic.model_validate(read("clinic.json")),
            patients=[Patient.model_validate(p) for p in read("patients.json")],
            medications=[Medication.model_validate(m) for m in read("medications.json")],
            appointments=[Appointment.model_validate(a) for a in read("appointments.json")],
        )

    # --- lookups -------------------------------------------------------------------------

    def patient(self, patient_id: str) -> Patient | None:
        return next((p for p in self.patients if p.id == patient_id), None)

    def medications_for(self, patient_id: str) -> list[Medication]:
        return [m for m in self.medications if m.patient_id == patient_id]

    def appointment(self, appointment_id: str) -> Appointment | None:
        return next((a for a in self.appointments if a.id == appointment_id), None)

    def booked_appointments(self) -> list[Appointment]:
        return [a for a in self.appointments if a.status == "booked"]

    # --- writes --------------------------------------------------------------------------

    def new_appointment_id(self) -> str:
        appointment_id = f"A{self._next_appointment_number:03d}"
        self._next_appointment_number += 1
        return appointment_id

    def add_appointment(self, appointment: Appointment) -> None:
        self.appointments.append(appointment)

    def _max_appointment_number(self) -> int:
        numbers = [int(a.id[1:]) for a in self.appointments if a.id[1:].isdigit()]
        return max(numbers, default=0)
