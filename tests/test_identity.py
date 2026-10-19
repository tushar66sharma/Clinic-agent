"""Identity and privacy rules, using the sample messages' real senders."""

from datetime import date

from edvak_forge.clinic.identity import (
    find_patients,
    normalize_email,
    normalize_name,
    normalize_phone,
    verify_sender,
)


def test_normalisation():
    assert normalize_name("Kevin O'Brien") == "kevin obrien"
    assert normalize_name("  José   Pérez ") == "jose perez"
    assert normalize_phone("+1 (555) 010-2") == "5550102"


def test_m001_patient_from_phone_on_file_is_verified(repo):
    v = verify_sender(repo.patient("P002"), from_name="Robert Chen", from_contact="555-0102")
    assert v.verified and v.relationship == "self" and v.method == "contact_on_file"


def test_m011_unknown_email_and_wrong_dob_is_not_verified(repo):
    # Robert Chen's real DOB is 1971-11-02; the sender says 1971-11-20 from a new email.
    v = verify_sender(repo.patient("P002"), from_name="Robert Chen",
                      from_contact="rchen.new@example.org", stated_dob=date(1971, 11, 20))
    assert not v.verified
    assert v.reason == "stated_dob_does_not_match_record"


def test_wrong_dob_blocks_even_from_phone_on_file(repo):
    v = verify_sender(repo.patient("P002"), from_name="Robert Chen", from_contact="555-0102",
                      stated_dob=date(1971, 11, 20))
    assert not v.verified


def test_name_and_correct_dob_verifies(repo):
    v = verify_sender(repo.patient("P002"), from_name="Robert Chen",
                      from_contact="rchen.new@example.org", stated_dob=date(1971, 11, 2))
    assert v.verified and v.method == "name_and_dob"


def test_name_alone_from_unknown_contact_is_not_verified(repo):
    v = verify_sender(repo.patient("P002"), from_name="Robert Chen",
                      from_contact="someone@example.org")
    assert not v.verified


def test_m014_caregiver_phone_on_file_is_verified(repo):
    v = verify_sender(repo.patient("P017"), from_name="Claire Ellis", from_contact="555-0177")
    assert v.verified and v.relationship == "caregiver"


def test_m015_guardian_sharing_childs_phone_is_verified_as_caregiver(repo):
    v = verify_sender(repo.patient("P009"), from_name="Anna Rossi", from_contact="555-0109")
    assert v.verified and v.relationship == "caregiver"


def test_m027_third_party_not_on_file_is_not_verified(repo):
    matches = find_patients(repo.patients, name="Grace Park")
    assert [m.patient_id for m in matches] == ["P013"]
    v = verify_sender(repo.patient("P013"), from_name="Mike", from_contact="555-0888")
    assert not v.verified


def test_m007_new_person_matches_nobody(repo):
    assert find_patients(repo.patients, name="Jessica Parker",
                         email="jess.parker@example.net") == []


def test_m038_spam_sender_matches_nobody(repo):
    assert find_patients(repo.patients, name="BillingPro Solutions",
                         email="offers@billingpro.example") == []


def test_find_by_caregiver_phone(repo):
    matches = find_patients(repo.patients, phone="555-0177")
    assert matches[0].patient_id == "P017"
    assert "caregiver_phone" in matches[0].reasons


def test_contact_match_ranks_above_dob_only(repo):
    matches = find_patients(repo.patients, phone="555-0102", dob=date(1958, 3, 14))
    assert matches[0].patient_id == "P002"  # phone beats a DOB-only match (P001)


def test_known_phone_with_a_different_name_is_verified_but_flagged(repo):
    # Found during manual testing: "arpita" writing from Grace Park's phone.
    v = verify_sender(repo.patient("P013"), from_name="arpita", from_contact="555-0113")
    assert v.verified and v.method == "contact_on_file"
    assert v.reason == "sender_contact_on_file_but_name_differs"
    same = verify_sender(repo.patient("P013"), from_name="Grace Park", from_contact="555-0113")
    assert same.reason == "sender_contact_on_file"


def test_pasted_email_debris_is_ignored(repo):
    # Found in manual testing: "mailto:" copied from a link made a real patient unverified.
    for contact in ["mailto:fatima.hassan@example.com", "  Fatima.Hassan@Example.com\t",
                    "<fatima.hassan@example.com>", "mailto:fatima.hassan@example.com?subject=refill"]:
        v = verify_sender(repo.patient("P015"), from_name="Fatima Hassan\t", from_contact=contact)
        assert v.verified, contact
    assert normalize_email("mailto:A@B.com") == "a@b.com"
