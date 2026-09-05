"""The five offline helper tools."""

from __future__ import annotations

import json

import pytest
from toolbox import date_parse, html_to_text, json_validate, number_parse, regex_extract


def load(result: str) -> dict:
    assert not result.startswith("ERROR:"), result
    return json.loads(result)


# ---------------------------------------------------------------- html_to_text


def test_html_to_text_drops_markup_scripts_and_styles():
    html = (
        "<html><head><style>.a{color:red}</style></head><body>"
        "<script>alert('x')</script>"
        "<h1>Widget Jam</h1><p>Prize pool: $10,000</p>"
        "<ul><li>Track A</li><li>Track B</li></ul>"
        "</body></html>"
    )
    text = html_to_text.run({"html": html})
    assert "Widget Jam" in text
    assert "Prize pool: $10,000" in text
    assert "Track A" in text and "Track B" in text
    assert "alert" not in text
    assert "color:red" not in text
    assert "<" not in text


def test_html_to_text_puts_block_elements_on_their_own_lines():
    text = html_to_text.run({"html": "<p>one</p><p>two</p><div>three<br>four</div>"})
    assert [line for line in text.splitlines() if line] == [
        "one",
        "two",
        "three",
        "four",
    ]
    # Blocks are separated by at most one blank line, never a wall of them.
    assert "\n\n\n" not in text


def test_html_to_text_decodes_entities_and_truncates():
    assert html_to_text.run({"html": "<p>A &amp; B</p>"}) == "A & B"
    result = html_to_text.run({"html": "<p>" + "x" * 100 + "</p>", "max_chars": 10})
    assert result.startswith("x" * 10)
    assert "truncated" in result


def test_html_to_text_reports_a_missing_argument_instead_of_raising():
    assert html_to_text.run({}).startswith("ERROR:")


# --------------------------------------------------------------- regex_extract


def test_regex_extract_returns_whole_matches_when_there_are_no_groups():
    result = load(regex_extract.run({"pattern": r"#\d+", "text": "see #12 and #340"}))
    assert result["matches"] == ["#12", "#340"]
    assert result["match_count"] == 2


def test_regex_extract_returns_groups_and_can_select_one():
    payload = {"pattern": r"(\w+)=(\d+)", "text": "a=1 b=22"}
    assert load(regex_extract.run(payload))["matches"] == [["a", "1"], ["b", "22"]]
    assert load(regex_extract.run({**payload, "group": 2}))["matches"] == ["1", "22"]


def test_regex_extract_honours_flags_and_max_matches():
    assert load(regex_extract.run({"pattern": "abc", "text": "ABC", "flags": "i"}))[
        "matches"
    ] == ["ABC"]
    assert load(regex_extract.run({"pattern": "abc", "text": "ABC"}))["matches"] == []
    capped = load(
        regex_extract.run({"pattern": r"\d", "text": "12345", "max_matches": 2})
    )
    assert capped["matches"] == ["1", "2"]


def test_regex_extract_reports_a_bad_pattern_or_flag():
    assert regex_extract.run({"pattern": "([", "text": "x"}).startswith("ERROR:")
    assert "z" in regex_extract.run({"pattern": "a", "text": "a", "flags": "z"})


# ------------------------------------------------------------------ date_parse


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024-03-07", "2024-03-07"),
        ("Deadline is 7 March 2024 sharp", "2024-03-07"),
        ("March 7th, 2024", "2024-03-07"),
        ("7th of March, 2024", "2024-03-07"),
        ("Starts 03/07/2024", "2024-03-07"),
        ("Sep 2024", "2024-09-01"),
    ],
)
def test_date_parse_normalises_common_shapes(text, expected):
    assert load(date_parse.run({"text": text}))["date"] == expected


def test_date_parse_dayfirst_switches_numeric_order():
    assert (
        load(date_parse.run({"text": "03/07/2024", "dayfirst": True}))["date"]
        == "2024-07-03"
    )


def test_date_parse_extracts_a_trailing_time_and_timezone_without_converting():
    result = load(date_parse.run({"text": "2024-03-07 5:30 pm PST"}))
    assert result["time"] == "17:30"
    assert result["timezone"] == "PST"
    assert result["date"] == "2024-03-07"


def test_date_parse_reports_a_missing_year_rather_than_guessing():
    result = load(date_parse.run({"text": "submissions close on March 7th"}))
    assert result["date"] is None
    assert "year" in result["note"]


def test_date_parse_rejects_an_impossible_date_and_text_with_no_date():
    assert load(date_parse.run({"text": "2024-02-31"}))["date"] is None
    assert date_parse.run({"text": "no date at all here"}).startswith("ERROR:")


# --------------------------------------------------------------- json_validate


def test_json_validate_accepts_good_json_and_reports_its_shape():
    result = load(json_validate.run({"text": '{"b": 1, "a": 2}'}))
    assert result["valid"] is True
    assert result["top_level_type"] == "object"
    assert result["keys"] == ["a", "b"]
    assert result["parsed"] == {"a": 2, "b": 1}


def test_json_validate_unwraps_a_fenced_block():
    assert load(json_validate.run({"text": '```json\n{"a": 1}\n```'}))["valid"] is True


def test_json_validate_names_the_syntax_error_with_a_position():
    result = json_validate.run({"text": '{"a": 1,}'})
    assert result.startswith("ERROR:")
    assert "line 1" in result and "column" in result


def test_json_validate_flags_missing_keys_and_the_wrong_top_level_type():
    result = load(
        json_validate.run({"text": '{"a": 1}', "required_keys": ["a", "b", "c"]})
    )
    assert result["valid"] is False
    assert "b, c" in result["errors"][0]

    result = load(json_validate.run({"text": "[1, 2]", "expect_type": "object"}))
    assert result["valid"] is False
    assert "expected object" in result["errors"][0]


# --------------------------------------------------------------- number_parse


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("12,500 attendees", 12500.0),
        ("$1.2M in prizes", 1_200_000.0),
        ("3.5 billion", 3_500_000_000.0),
        ("5 lakh", 500_000.0),
        ("2 crore", 20_000_000.0),
        ("-4.5", -4.5),
    ],
)
def test_number_parse_resolves_separators_and_magnitudes(text, value):
    assert load(number_parse.run({"text": text}))["numbers"][0]["value"] == value


def test_number_parse_reports_currency_and_percent_without_converting():
    result = load(number_parse.run({"text": "€250 and 15%"}))
    assert result["numbers"][0]["currency"] == "EUR"
    assert result["numbers"][1]["value"] == 15.0
    assert result["numbers"][1]["is_percent"] is True


def test_number_parse_can_filter_by_currency_and_take_only_the_first():
    result = load(number_parse.run({"text": "$100 and £200", "currency": "GBP"}))
    assert [n["value"] for n in result["numbers"]] == [200.0]
    first = load(number_parse.run({"text": "1 2 3", "first_only": True}))
    assert first["count"] == 1


def test_number_parse_returns_an_empty_list_rather_than_inventing_a_number():
    result = load(number_parse.run({"text": "no digits here"}))
    assert result["count"] == 0
    assert result["numbers"] == []


# ------------------------------------------------------------------- contracts


@pytest.mark.parametrize(
    "module", [html_to_text, regex_extract, date_parse, json_validate, number_parse]
)
def test_every_offline_tool_exposes_the_tool_contract(module):
    tool = module.TOOL
    assert set(tool) == {"name", "description", "input_schema"}
    assert tool["input_schema"]["type"] == "object"
    assert callable(module.run)
    assert isinstance(module.run({}), str)
