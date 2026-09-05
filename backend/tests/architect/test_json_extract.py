from __future__ import annotations

import pytest
from architect.json_extract import JSONExtractionError, extract_json_object


def test_extracts_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extracts_from_a_fenced_block():
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('```\n{"a": 1}\n```') == {"a": 1}


def test_extracts_from_surrounding_prose():
    text = 'Sure, here you go:\n{"a": 1, "b": [1, 2]}\nHope that helps!'
    assert extract_json_object(text) == {"a": 1, "b": [1, 2]}


def test_rejects_a_non_object_top_level():
    with pytest.raises(JSONExtractionError):
        extract_json_object("[1, 2, 3]")


def test_rejects_unparseable_text():
    with pytest.raises(JSONExtractionError):
        extract_json_object("not json at all")
