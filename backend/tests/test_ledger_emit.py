from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.ledger.emit import emit, read
from backend.tests.sample_events import VALID_PAYLOADS


def test_emit_inserts_a_valid_payload(conn):
    event_id = emit(
        "run_started",
        agent_id="a1",
        agent_version=0,
        run_id="r_1",
        conn=conn,
        **VALID_PAYLOADS["run_started"],
    )
    assert event_id > 0

    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    assert row["kind"] == "run_started"
    assert row["agent_id"] == "a1"
    assert row["agent_version"] == 0
    assert row["run_id"] == "r_1"
    assert row["lever"] is None
    assert row["ts"].endswith("Z")
    assert json.loads(row["payload"])["case_count"] == 42


def test_emit_rejects_an_invalid_payload_and_writes_nothing(conn):
    with pytest.raises(ValidationError):
        emit("run_started", agent_id="a1", conn=conn, split="train")  # missing keys
    assert conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0


def test_emit_rejects_an_unknown_kind(conn):
    with pytest.raises(KeyError):
        emit("not_a_kind", conn=conn)
    assert conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0


def test_emit_rejects_an_unknown_lever(conn):
    with pytest.raises(ValueError):
        emit(
            "run_started",
            agent_id="a1",
            lever="vibes",
            conn=conn,
            payload=VALID_PAYLOADS["run_started"],
        )


def test_lever_column_mirrors_the_payload(conn):
    event_id = emit(
        "fix_proposed", agent_id="a1", conn=conn, payload=VALID_PAYLOADS["fix_proposed"]
    )
    row = conn.execute("SELECT lever FROM events WHERE id = ?", (event_id,)).fetchone()
    assert row["lever"] == "memory"


def test_lever_argument_is_copied_into_the_payload(conn):
    """`lever=` collides with the fix_proposed payload key; emit reconciles them."""
    payload = {k: v for k, v in VALID_PAYLOADS["fix_proposed"].items() if k != "lever"}
    event_id = emit("fix_proposed", agent_id="a1", lever="memory", conn=conn, payload=payload)
    row = conn.execute("SELECT lever, payload FROM events WHERE id = ?", (event_id,)).fetchone()
    assert row["lever"] == "memory"
    assert json.loads(row["payload"])["lever"] == "memory"


def test_payload_keys_that_collide_with_parameters(conn):
    """`kind` is a payload key of drift_detected; it goes through payload=."""
    event_id = emit(
        "drift_detected", agent_id="a1", conn=conn, payload=VALID_PAYLOADS["drift_detected"]
    )
    row = conn.execute("SELECT kind, payload FROM events WHERE id = ?", (event_id,)).fetchone()
    assert row["kind"] == "drift_detected"
    assert json.loads(row["payload"])["kind"] == "loop"


def test_every_kind_can_be_emitted(conn):
    for kind, payload in VALID_PAYLOADS.items():
        emit(kind, agent_id="a1", conn=conn, payload=payload)
    kinds = [row["kind"] for row in conn.execute("SELECT kind FROM events ORDER BY id")]
    assert kinds == list(VALID_PAYLOADS)


def test_read_filters_and_parses_payloads(conn):
    first = emit(
        "run_started", agent_id="a1", run_id="r_1", conn=conn, payload=VALID_PAYLOADS["run_started"]
    )
    emit(
        "case_result", agent_id="a1", run_id="r_1", conn=conn, payload=VALID_PAYLOADS["case_result"]
    )
    emit(
        "run_started", agent_id="a2", run_id="r_2", conn=conn, payload=VALID_PAYLOADS["run_started"]
    )

    assert [e["agent_id"] for e in read(agent_id="a1", conn=conn)] == ["a1", "a1"]
    assert [e["kind"] for e in read(kind="run_started", conn=conn)] == [
        "run_started",
        "run_started",
    ]
    assert [e["run_id"] for e in read(run_id="r_2", conn=conn)] == ["r_2"]
    assert [e["id"] for e in read(since=first, conn=conn)] == [first + 1, first + 2]

    events = read(kind="case_result", conn=conn)
    assert events[0]["payload"]["rules_injected"] == ["rule_1a2b3c"]


def test_read_since_accepts_a_timestamp(conn):
    emit(
        "run_started",
        agent_id="a1",
        ts="2026-09-01T00:00:00Z",
        conn=conn,
        payload=VALID_PAYLOADS["run_started"],
    )
    emit(
        "run_started",
        agent_id="a1",
        ts="2026-09-05T00:00:00Z",
        conn=conn,
        payload=VALID_PAYLOADS["run_started"],
    )
    assert len(read(since="2026-09-03T00:00:00Z", conn=conn)) == 1


def test_ledger_module_never_updates_or_deletes():
    import inspect

    from backend.ledger import emit as module

    source = inspect.getsource(module).upper()
    assert "DELETE FROM" not in source
    assert "UPDATE EVENTS" not in source
