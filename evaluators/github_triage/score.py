"""Deterministic, offline scorer for the `github_triage` evaluator.

    score(expected, actual) -> {"passed": bool, "score": float, "notes": str}

Grading (PLAN.md 0.1 / 4.3):

* ``labelF1``   set F1 over ``labels`` (both sides empty -> 1.0)
* ``component`` 1.0 iff the ``component`` sets are equal, else 0.0
* ``priority``  1.0 iff equal case-insensitively (absent actual -> ``"none"``)
* ``passed``    iff ``labelF1 >= 0.8`` **and** component is exact
* ``score``     ``0.5*labelF1 + 0.3*component + 0.2*priority``

``notes`` is a normalized, sorted, ``;``-separated list of what was wrong, e.g.
``"extra_label:enhancement;missing_label:bug"``. The runtime builds
``failure_signature`` from it and the improver groups failures on it, so the
vocabulary must stay stable: ``missing_label:<name>``, ``extra_label:<name>``,
``component_mismatch``, ``priority_mismatch``, ``no_output``, ``ok``.

Stdlib only. No network, no clock, no randomness.
"""

from __future__ import annotations

PASS_LABEL_F1 = 0.8
W_LABELS = 0.5
W_COMPONENT = 0.3
W_PRIORITY = 0.2


def _as_label_set(value: object) -> set[str]:
    """Normalize a label-ish field to a set of lowercase names.

    A bare string is accepted as a one-element list, which is the most common
    shape an agent gets wrong for ``component``.
    """
    if value is None:
        return set()
    if isinstance(value, str):
        items: list[object] = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    else:
        return set()
    out = set()
    for item in items:
        if isinstance(item, str):
            name = item.strip().lower()
            if name:
                out.add(name)
    return out


def _as_priority(value: object) -> str:
    if value is None:
        return "none"
    if not isinstance(value, str):
        return "none"
    text = value.strip().upper()
    if not text or text == "NONE":
        return "none"
    return text


def _f1(expected: set[str], actual: set[str]) -> float:
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    overlap = len(expected & actual)
    if not overlap:
        return 0.0
    precision = overlap / len(actual)
    recall = overlap / len(expected)
    return 2 * precision * recall / (precision + recall)


def score(expected: dict, actual: dict) -> dict:
    """Grade one `github_triage` case. See the module docstring."""
    if not isinstance(actual, dict):
        return {"passed": False, "score": 0.0, "notes": "no_output"}
    if not isinstance(expected, dict):
        expected = {}

    exp_labels = _as_label_set(expected.get("labels"))
    act_labels = _as_label_set(actual.get("labels"))
    label_f1 = _f1(exp_labels, act_labels)

    exp_component = _as_label_set(expected.get("component"))
    act_component = _as_label_set(actual.get("component"))
    component = 1.0 if exp_component == act_component else 0.0

    exp_priority = _as_priority(expected.get("priority"))
    act_priority = _as_priority(actual.get("priority"))
    priority = 1.0 if exp_priority == act_priority else 0.0

    notes = [f"missing_label:{name}" for name in exp_labels - act_labels]
    notes += [f"extra_label:{name}" for name in act_labels - exp_labels]
    if not component:
        notes.append("component_mismatch")
    if not priority:
        notes.append("priority_mismatch")

    total = W_LABELS * label_f1 + W_COMPONENT * component + W_PRIORITY * priority
    return {
        "passed": bool(label_f1 >= PASS_LABEL_F1 and component == 1.0),
        "score": round(total, 6),
        "notes": ";".join(sorted(notes)) if notes else "ok",
    }
