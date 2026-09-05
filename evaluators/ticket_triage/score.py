"""Deterministic, offline scorer for the `ticket_triage` evaluator.

    score(expected, actual) -> {"passed": bool, "score": float, "notes": str}

Three fields are graded, all equally: ``category``, ``priority``, ``needs_human``.

* **``passed``** iff all three match.
* **``score``** = fraction of the three that matched (0.0, 0.333, 0.667, 1.0).
* A non-dict / missing output scores 0 with ``notes = "no_output"``.

``notes`` is a normalized, sorted, ``;``-separated list so the runtime's
``failure_signature`` and the improver's failure grouping stay stable:
``category_mismatch:<expected>-><actual>``, ``priority_mismatch:<expected>-><actual>``,
``needs_human_mismatch:<expected>-><actual>``, ``no_output``, ``ok``. An absent or
unparseable field is reported as ``missing`` on the actual side.

Stdlib only. No network, no clock, no randomness.
"""

from __future__ import annotations

CATEGORIES = ("billing", "bug", "feature", "account", "other")
PRIORITIES = ("p0", "p1", "p2", "p3")

MISSING = "missing"

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


def _as_text(value: object) -> str:
    if isinstance(value, str):
        text = value.strip().lower()
        if text:
            return text
    return MISSING


def _as_bool_text(value: object) -> str:
    """`needs_human` normalized to `"true"` / `"false"` / `"missing"`."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):  # 0/1 from a loosely typed agent
        return "true" if value else "false"
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return "true"
        if text in _FALSE:
            return "false"
    return MISSING


def score(expected: dict, actual: dict) -> dict:
    """Grade one `ticket_triage` case. See the module docstring."""
    if not isinstance(actual, dict):
        return {"passed": False, "score": 0.0, "notes": "no_output"}
    if not isinstance(expected, dict):
        expected = {}

    fields = (
        ("category", _as_text(expected.get("category")), _as_text(actual.get("category"))),
        ("priority", _as_text(expected.get("priority")), _as_text(actual.get("priority"))),
        (
            "needs_human",
            _as_bool_text(expected.get("needs_human")),
            _as_bool_text(actual.get("needs_human")),
        ),
    )

    notes = [f"{name}_mismatch:{exp}->{act}" for name, exp, act in fields if exp != act]
    matched = len(fields) - len(notes)

    return {
        "passed": not notes,
        "score": round(matched / len(fields), 6),
        "notes": ";".join(sorted(notes)) if notes else "ok",
    }
