from backend.runtime.signature import (
    DRIFT_SIGNATURE_PREFIX,
    bad_output_signature,
    drift_signature,
    failure_signature,
    missing_expected_keys,
)


def test_identical_failures_dedupe_across_runs():
    a = failure_signature(score_notes="component mismatch: expected 'cli', got 'ui'")
    b = failure_signature(score_notes="component mismatch: expected 'cli', got 'ui'")
    assert a == b


def test_numbers_are_stripped_so_case_specific_ids_do_not_split_groups():
    a = failure_signature(score_notes="label f1 0.25 below threshold on issue 1471")
    b = failure_signature(score_notes="label f1 0.80 below threshold on issue 992")
    assert a == b
    assert not any(ch.isdigit() for ch in a)


def test_whitespace_collapsed_and_lowercased():
    sig = failure_signature(score_notes="  Component\n\tMISMATCH   here ")
    assert sig == "component mismatch here"


def test_parts_are_combined_in_a_stable_order():
    sig = failure_signature(
        score_notes="missing fields",
        first_tool_error="ValueError: bad page",
        missing_keys=["priority", "component"],
    )
    assert (
        sig
        == "missing fields | tool_error valueerror bad page | missing component,priority"
    )


def test_missing_keys_order_does_not_matter():
    a = failure_signature(missing_keys=["b", "a"])
    b = failure_signature(missing_keys=["a", "b"])
    assert a == b


def test_empty_inputs_produce_a_named_unknown_signature():
    assert failure_signature() == "unknown_failure"
    assert failure_signature(score_notes="   ", missing_keys=[]) == "unknown_failure"


def test_signature_is_capped_at_120_chars():
    sig = failure_signature(score_notes="word " * 200)
    assert len(sig) <= 120


def test_drift_and_bad_output_signatures():
    assert drift_signature("loop") == "drift:loop"
    assert drift_signature("budget").startswith(DRIFT_SIGNATURE_PREFIX)
    assert bad_output_signature() == "bad_output"


def test_missing_expected_keys_reports_absent_and_null_keys():
    expected = {"labels": ["bug"], "component": "cli", "priority": "p1"}
    actual = {"labels": ["bug"], "priority": None}
    assert missing_expected_keys(expected, actual) == ["component", "priority"]


def test_missing_expected_keys_handles_non_dict_actual():
    assert missing_expected_keys({"a": 1, "b": 2}, None) == ["a", "b"]
