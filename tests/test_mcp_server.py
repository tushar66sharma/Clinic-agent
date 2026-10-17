"""The MCP server end to end, through a real MCP client connected in-process."""

import json

from mcp import Client

from edvak_forge.mcp_server import ADMIN_TOOL_PREFIX, build_server

EXPECTED_AGENT_TOOLS = {
    "find_patient", "verify_sender", "get_patient_profile", "get_medications",
    "check_refill_eligibility", "prepare_refill_request", "list_appointments",
    "find_free_slots", "book_appointment", "reschedule_appointment", "cancel_appointment",
    "get_clinic_info", "check_clinic_open", "route_to_queue", "draft_reply",
    "flag_suspicious_instruction",
}


def payload(result) -> dict:
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


async def test_lists_all_tools():
    server, _ = build_server()
    async with Client(server) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
    assert EXPECTED_AGENT_TOOLS <= tools
    assert {t for t in tools if t.startswith(ADMIN_TOOL_PREFIX)} == {
        "admin_reset_state", "admin_set_clock", "admin_get_run_log"}


async def test_refill_flow_over_mcp():
    server, _ = build_server()
    async with Client(server) as client:
        found = payload(await client.call_tool("find_patient", {"phone": "555-0102"}))
        assert found["matches"][0]["patient_id"] == "P002"

        v = payload(await client.call_tool("verify_sender", {
            "patient_id": "P002", "from_name": "Robert Chen", "from_contact": "555-0102"}))
        token = v["verification_token"]

        check = payload(await client.call_tool("check_refill_eligibility", {
            "patient_id": "P002", "verification_token": token, "medication": "lisinopril"}))
        assert check["decisions"][0]["status"] == "eligible"

        prep = payload(await client.call_tool("prepare_refill_request", {
            "patient_id": "P002", "verification_token": token, "medication": "lisinopril",
            "message_id": "M001"}))
        assert prep["ok"]

        log = payload(await client.call_tool("admin_get_run_log", {}))
        assert len(log["refill_requests"]) == 1


async def test_reset_restores_original_schedule():
    server, _ = build_server()
    async with Client(server) as client:
        v = payload(await client.call_tool("verify_sender", {
            "patient_id": "P011", "from_name": "Hannah Lee", "from_contact": "555-0111"}))
        await client.call_tool("cancel_appointment", {
            "appointment_id": "A017", "patient_id": "P011",
            "verification_token": v["verification_token"], "message_id": "M022"})
        await client.call_tool("admin_reset_state", {})
        log = payload(await client.call_tool("admin_get_run_log", {}))
        assert log["appointment_changes"] == []


async def test_unverified_call_is_refused_over_mcp():
    server, _ = build_server()
    async with Client(server) as client:
        r = payload(await client.call_tool("get_medications", {
            "patient_id": "P002", "verification_token": "made-up"}))
    assert r["ok"] is False and r["error"]["code"] == "verification_required"


async def test_invalid_enum_is_rejected_by_schema():
    server, _ = build_server()
    async with Client(server) as client:
        r = await client.call_tool("route_to_queue", {
            "message_id": "M001", "queue": "nowhere", "reason": "x"})
    assert r.is_error
