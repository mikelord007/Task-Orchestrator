"""Every event kind in PLAN.md section 4.1 (+ section 0.2) must validate."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.tests.sample_events import VALID_PAYLOADS
from contracts.events import EVENT_KINDS, PAYLOAD_MODELS, Lever, validate_payload


def test_every_kind_in_the_table_has_a_model():
    assert set(PAYLOAD_MODELS) == set(EVENT_KINDS)
    assert set(VALID_PAYLOADS) == set(EVENT_KINDS), "add the new kind to VALID_PAYLOADS"


@pytest.mark.parametrize("kind", sorted(VALID_PAYLOADS))
def test_valid_payload_round_trips(kind: str):
    out = validate_payload(kind, VALID_PAYLOADS[kind])
    assert isinstance(out, dict)
    for key in VALID_PAYLOADS[kind]:
        assert key in out


@pytest.mark.parametrize("kind", sorted(VALID_PAYLOADS))
def test_dropping_any_required_key_is_rejected(kind: str):
    model = PAYLOAD_MODELS[kind]
    required = [name for name, f in model.model_fields.items() if f.is_required()]
    assert required, f"{kind} declares no required keys"
    for name in required:
        payload = {k: v for k, v in VALID_PAYLOADS[kind].items() if k != name}
        with pytest.raises(ValidationError):
            validate_payload(kind, payload)


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        validate_payload("not_a_kind", {})


def test_levers_are_the_five_from_section_4_1():
    assert {lever.value for lever in Lever} == {
        "prompt",
        "tools",
        "memory",
        "orchestration",
        "routing",
    }


def test_case_result_carries_the_section_0_2_additions():
    out = validate_payload("case_result", VALID_PAYLOADS["case_result"])
    assert out["tool_calls"] == 3
    assert out["tool_errors"] == 1
    assert out["rules_injected"] == ["rule_1a2b3c"]


def test_enums_are_enforced():
    bad = dict(VALID_PAYLOADS["drift_detected"], kind="wandering")
    with pytest.raises(ValidationError):
        validate_payload("drift_detected", bad)
