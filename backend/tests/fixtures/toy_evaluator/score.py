"""Toy scorer: every expected field must match exactly."""


def score(expected: dict, actual) -> dict:
    if not isinstance(actual, dict):
        return {"passed": False, "score": 0.0, "notes": "output was not a JSON object"}
    matched = [key for key in expected if actual.get(key) == expected[key]]
    missing = sorted(set(expected) - set(matched))
    return {
        "passed": len(matched) == len(expected),
        "score": len(matched) / max(1, len(expected)),
        "notes": "" if not missing else "field mismatch: " + ", ".join(missing),
    }
