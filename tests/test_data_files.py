"""The labelled message sets are well-formed, so evaluation results can be trusted."""

import json

import pytest

from edvak_forge.agent.schemas import ACTIONS, AgentResult
from edvak_forge.config import DEFAULT_DATA_DIR

SETS = ["sample", "extra", "exploratory", "manual"]
URGENCIES = {"emergency", "urgent", "routine"}
INTENTS = set(AgentResult.model_fields["intents"].annotation.__args__[0].__args__)


def load(name):
    return json.loads((DEFAULT_DATA_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", SETS)
def test_messages_and_labels_match(name):
    messages = load(f"messages_{name}.json")
    labels = load(f"labels_{name}.json")
    assert [m["id"] for m in messages] == [lab["id"] for lab in labels]
    assert len({m["id"] for m in messages}) == len(messages)
    for m in messages:
        assert m["body"].strip() and m["from_contact"] and m["received_at"]


@pytest.mark.parametrize("name", SETS)
def test_labels_use_the_brief_vocabulary(name):
    for lab in load(f"labels_{name}.json"):
        assert set(lab["expected_actions"]) <= set(ACTIONS), lab["id"]
        assert set(lab["accepted_urgency"]) <= URGENCIES, lab["id"]
        assert set(lab["intents"]) <= INTENTS, lab["id"]


@pytest.mark.parametrize("name", ["sample", "exploratory", "manual"])
def test_booking_details_refer_to_real_messages(name):
    ids = {m["id"] for m in load(f"messages_{name}.json")}
    details = load(f"label_details_{name}.json")
    for key, value in details.items():
        if key.startswith("_"):
            continue
        assert key in ids and "appointment" in value, key
