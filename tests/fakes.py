"""A scripted stand-in for a real LLM provider, so agent tests run offline and repeatably."""

from __future__ import annotations

import re

from edvak_forge.agent.schemas import Analysis, ReplyDraft
from edvak_forge.llm.base import LLMResponseError, Usage

BASE = dict(
    language="English", sender_role="patient", subject_patient_name=None, stated_dob=None,
    intents=["other"], urgency="routine", urgency_reason="", clinical_concern=None,
    needs_clinician=False, refill_medications=[], booking=None, reschedule_from_date=None,
    reschedule_from_description=None, reschedule_to=None, cancel_date=None, questions=[],
    question_date=None, billing_question=False, records_request=False, admin_request=None,
    suspicious_instruction=None,
)


def analysis(**overrides) -> Analysis:
    return Analysis.model_validate({**BASE, **overrides})


class FakeLLM:
    """`script` maps a substring of the message body to the Analysis to return.

    Replies echo the facts (always faithful) unless `bad_reply` is set.
    """

    provider = "fake"

    def __init__(self, script: dict[str, Analysis] | None = None, *, fail_analysis: bool = False,
                 bad_reply: str | None = None) -> None:
        self.script = script or {}
        self.fail_analysis = fail_analysis
        self.bad_reply = bad_reply
        self.usage = Usage()
        self.calls: list[str] = []

    def model_for(self, role: str) -> str:
        return f"fake-{role}"

    def complete_json(self, *, system, user, schema, role, max_tokens=1200):
        self.calls.append(role)
        self.usage.add(self.model_for(role), 100, 50)
        if schema is Analysis:
            if self.fail_analysis:
                raise LLMResponseError("scripted failure")
            body = re.search(r"<message>\n(.*)\n</message>", user, re.S).group(1)
            for needle, result in self.script.items():
                if needle in body:
                    return result
            return analysis()
        if schema is ReplyDraft:
            if self.bad_reply is not None:
                return ReplyDraft(reply=self.bad_reply)
            facts = user.split("facts:\n", 1)[1].split("\n\nYour previous", 1)[0]
            return ReplyDraft(reply=f"Hi there. {facts.replace('- ', '')} Maplewood Family Clinic")
        raise AssertionError(f"unexpected schema {schema}")
