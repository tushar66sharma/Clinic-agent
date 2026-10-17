"""Web API: endpoints, error format, access token, batch runs, static safety."""

import time

import pytest
from fastapi.testclient import TestClient

from edvak_forge.api.app import create_app
from edvak_forge.llm.base import LLMConfigError
from tests.fakes import FakeLLM, analysis


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("DEMO_ACCESS_TOKEN", raising=False)
    llm = FakeLLM({"lisinopril": analysis(intents=["refill"], refill_medications=["lisinopril"])})
    with TestClient(create_app(llm_factory=lambda: llm)) as c:
        yield c


def test_health_reports_ai_configuration(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["today"] == "2026-11-09"
    assert body["ai"]["configured"] is True and body["ai"]["provider"] == "fake"


def test_runs_without_ai_key_and_says_so(monkeypatch):
    monkeypatch.delenv("DEMO_ACCESS_TOKEN", raising=False)

    def broken():
        raise LLMConfigError("GROQ_API_KEY is not set.")

    with TestClient(create_app(llm_factory=broken)) as c:
        health = c.get("/api/health").json()
        assert health["ai"]["configured"] is False and "GROQ_API_KEY" in health["ai"]["error"]
        r = c.post("/api/messages/process", json={
            "from_name": "Aisha Johnson", "from_contact": "555-0103",
            "body": "Crushing chest pain and I feel dizzy"})
        assert r.json()["result"]["actions"] == ["escalate_emergency"]


def test_inbox_lists_sample_messages(client):
    body = client.get("/api/inbox/sample").json()
    assert len(body["messages"]) == 40 and body["messages"][0]["processed"] is None
    assert client.get("/api/inbox/nope").status_code == 404


def test_process_new_message(client):
    r = client.post("/api/messages/process", json={
        "channel": "sms", "from_name": "Robert Chen", "from_contact": "555-0102",
        "body": "Can I get my lisinopril refilled?"})
    assert r.status_code == 200
    item = r.json()
    assert item["message"]["id"] == "C001"
    assert item["result"]["actions"] == ["prepare_refill_for_approval"]
    assert any(c["tool"] == "prepare_refill_request" for c in item["trace"]["tool_trace"])
    assert client.get("/api/results/C001").status_code == 200
    queues = client.get("/api/queues").json()
    assert queues["refill_requests"][0]["patient_id"] == "P002"


def test_validation_errors_use_one_format(client):
    r = client.post("/api/messages/process", json={"from_name": "", "from_contact": "x",
                                                    "body": ""})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_input" and {f["field"] for f in err["fields"]} >= {"from_name", "body"}


def test_message_body_size_is_bounded(client):
    r = client.post("/api/messages/process", json={"from_name": "A", "from_contact": "555-0102",
                                                    "body": "x" * 2001})
    assert r.status_code == 422


def test_access_token_protects_actions(monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_TOKEN", "s3cret")
    with TestClient(create_app(llm_factory=lambda: FakeLLM())) as c:
        body = {"from_name": "A B", "from_contact": "555-0102", "body": "hello"}
        assert c.post("/api/messages/process", json=body).status_code == 401
        assert c.post("/api/messages/process", json=body,
                      headers={"X-Access-Token": "wrong"}).status_code == 401
        assert c.post("/api/messages/process", json=body,
                      headers={"X-Access-Token": "s3cret"}).status_code == 200
        assert c.get("/api/health").json()["access_token_required"] is True
        assert c.post("/api/state/reset").status_code == 401


def test_batch_run_completes_and_reset_clears(client):
    job = client.post("/api/runs", json={"set": "sample", "ids": ["M001", "M003", "M038"]}).json()
    for _ in range(100):
        job = client.get(f"/api/runs/{job['id']}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "finished" and job["done"] == 3
    inbox = client.get("/api/inbox/sample").json()["messages"]
    assert inbox[2]["processed"]["actions"] == ["escalate_emergency"]
    assert client.post("/api/state/reset").json() == {"ok": True}
    assert client.get("/api/results").json()["items"] == []


def test_schedule_shows_leave_and_closed_days(client):
    leave = client.get("/api/schedule", params={"day": "2026-11-18"}).json()
    okafor = next(p for p in leave["providers"] if p["id"] == "OKAFOR")
    assert okafor["on_leave"] is True
    holiday = client.get("/api/schedule", params={"day": "2026-11-27"}).json()
    assert holiday["open"] is False and holiday["closed_reason"] == "holiday"
    assert client.get("/api/schedule", params={"day": "soon"}).status_code == 422


def test_reports_are_listed_and_names_are_validated(client):
    items = client.get("/api/reports").json()["items"]
    assert any(i["name"] == "sample-40" for i in items)
    assert client.get("/api/reports/sample-40").json()["evaluation"]["headline"]["messages"] == 40
    assert client.get("/api/reports/..%2F..%2Fdata").status_code == 404


def test_unknown_api_route_is_json_404(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
