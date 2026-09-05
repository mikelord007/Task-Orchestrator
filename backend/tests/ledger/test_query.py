"""``query.events(since=)``: an event-id cursor or an ISO8601 timestamp.

Matches ``backend.ledger.emit.read()``, which already documents accepting
either -- ``GET /events?since=`` forwards whatever string arrives over HTTP,
so a digit string must be treated as an id cursor, not a timestamp.
"""

from __future__ import annotations

from backend.ledger import query
from backend.tests.ledger.seed import SeededLedger


def test_since_as_an_int_is_an_exclusive_id_cursor(seeded: SeededLedger) -> None:
    everything = query.events(seeded.conn)
    cursor_id = everything[2].id
    result = query.events(seeded.conn, since=cursor_id)
    assert [e.id for e in result] == [e.id for e in everything if e.id > cursor_id]


def test_since_as_a_digit_string_is_the_same_id_cursor(seeded: SeededLedger) -> None:
    everything = query.events(seeded.conn)
    cursor_id = everything[2].id
    by_int = query.events(seeded.conn, since=cursor_id)
    by_string = query.events(seeded.conn, since=str(cursor_id))
    assert [e.id for e in by_string] == [e.id for e in by_int]


def test_since_as_a_non_digit_string_is_still_a_timestamp_lower_bound(
    seeded: SeededLedger,
) -> None:
    everything = query.events(seeded.conn)
    midpoint_ts = everything[len(everything) // 2].ts
    result = query.events(seeded.conn, since=midpoint_ts)
    assert result
    assert all(e.ts >= midpoint_ts for e in result)
