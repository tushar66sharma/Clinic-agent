from datetime import date

import pytest

from edvak_forge.clinic.repository import ClinicRepository
from edvak_forge.clinic.service import ClinicService
from edvak_forge.config import DEFAULT_DATA_DIR

TODAY = date(2026, 11, 9)


@pytest.fixture
def repo() -> ClinicRepository:
    """A fresh copy of the clinic data for every test, so tests cannot affect each other."""
    return ClinicRepository.load(DEFAULT_DATA_DIR)


@pytest.fixture
def service(repo) -> ClinicService:
    return ClinicService(repo, TODAY)


def verified_token(service: ClinicService, patient_id: str) -> str:
    """Verify using the patient's own phone on file and return the token."""
    p = service.repo.patient(patient_id)
    result = service.verify_sender(patient_id, p.name, p.phone)
    assert result["verified"], result
    return result["verification_token"]
