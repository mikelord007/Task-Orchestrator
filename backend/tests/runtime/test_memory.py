import json

from backend.runtime import memory as mem


def rule(rid, text, keywords, **extra):
    return {
        "id": rid,
        "rule": text,
        "scope_keywords": keywords,
        "evidence_case_ids": [],
        "confidence": extra.pop("confidence", 0.5),
        "hits": extra.pop("hits", 0),
        "misses": extra.pop("misses", 0),
        "created_version": 0,
        "source": "reflection",
        **extra,
    }


# -- tokenizer ----------------------------------------------------------


def test_tokenize_splits_on_non_alphanumerics_and_lowercases():
    assert mem.tokenize("ConPTY/Windows: resize-bug (v2)") == {
        "conpty",
        "windows",
        "resize",
        "bug",
        "v2",
    }


def test_tokenize_handles_empty_and_none():
    assert mem.tokenize("") == set()
    assert mem.tokenize(None) == set()


def test_case_text_flattens_nested_case_input():
    text = mem.case_text({"title": "Crash on Windows", "body": {"detail": ["ConPTY", 42]}})
    tokens = mem.tokenize(text)
    assert {"crash", "windows", "conpty", "42"} <= tokens


# -- selection ----------------------------------------------------------


def test_selects_top_k_rules_by_keyword_overlap():
    rules = [
        rule("r1", "windows conpty rule", ["windows", "conpty"]),
        rule("r2", "billing rule", ["billing", "invoice"]),
        rule("r3", "windows rule", ["windows"]),
    ]
    selected = mem.select_rules(rules, "Terminal crashes on Windows with ConPTY", k=12)
    assert [r["id"] for r in selected] == ["r1", "r3"]


def test_rules_with_no_overlap_are_not_injected():
    rules = [rule("r1", "billing", ["billing"])]
    assert mem.select_rules(rules, "windows crash", k=12) == []


def test_rules_without_scope_keywords_are_treated_as_global_but_rank_last():
    rules = [
        rule("r_global", "always answer with json", []),
        rule("r_match", "windows rule", ["windows"]),
    ]
    selected = mem.select_rules(rules, "windows crash", k=12)
    assert [r["id"] for r in selected] == ["r_match", "r_global"]


def test_top_k_is_respected():
    rules = [rule(f"r{i}", "x", ["windows"], confidence=0.5) for i in range(20)]
    selected = mem.select_rules(rules, "windows", k=12)
    assert len(selected) == 12


def test_ties_break_on_confidence_then_net_hits_then_id_for_determinism():
    rules = [
        rule("rb", "b", ["windows"], confidence=0.9),
        rule("ra", "a", ["windows"], confidence=0.9, hits=5),
        rule("rc", "c", ["windows"], confidence=0.1),
    ]
    selected = mem.select_rules(rules, "windows", k=12)
    assert [r["id"] for r in selected] == ["ra", "rb", "rc"]


def test_demoted_rules_are_skipped_whether_flagged_on_disk_or_in_the_ledger():
    rules = [
        rule("r1", "a", ["windows"], demoted=True),
        rule("r2", "b", ["windows"]),
        rule("r3", "c", ["windows"]),
    ]
    selected = mem.select_rules(rules, "windows", k=12, demoted_ids={"r3"})
    assert [r["id"] for r in selected] == ["r2"]


# -- injection block ----------------------------------------------------


def test_block_contains_every_tool_note_and_the_selected_rules():
    notes = [
        {"id": "tn1", "tool": "list_issues", "note": "paginates at 100"},
        {"id": "tn2", "tool": "get_file", "note": "returns raw text"},
    ]
    rules = [rule("r1", "windows reports get platform:windows", ["windows"])]
    block = mem.build_memory_block(notes, rules)
    assert mem.MEMORY_BLOCK_START in block
    assert mem.MEMORY_BLOCK_END in block
    assert "paginates at 100" in block
    assert "returns raw text" in block
    assert "windows reports get platform:windows" in block
    assert "[tn1]" in block and "[r1]" in block


def test_empty_memory_produces_no_block():
    assert mem.build_memory_block([], []) == ""


def test_inject_appends_the_block_to_the_system_prompt():
    prompt = mem.inject_into_prompt("You are a triage agent.", "MEMORY")
    assert prompt.startswith("You are a triage agent.")
    assert prompt.rstrip().endswith("MEMORY")
    assert mem.inject_into_prompt("base", "") == "base"


# -- disk ---------------------------------------------------------------


def test_load_memory_reads_the_three_jsonl_files_and_tolerates_missing(tmp_path):
    pkg = tmp_path / "v0"
    (pkg / "memory").mkdir(parents=True)
    (pkg / "memory" / "rules.jsonl").write_text(
        json.dumps(rule("r1", "a", ["x"])) + "\n\n" + json.dumps(rule("r2", "b", ["y"])) + "\n",
        encoding="utf-8",
    )
    loaded = mem.load_memory(pkg)
    assert [r["id"] for r in loaded.rules] == ["r1", "r2"]
    assert loaded.tool_notes == []
    assert loaded.episodes == []


def test_load_memory_of_a_package_without_a_memory_dir(tmp_path):
    loaded = mem.load_memory(tmp_path / "v0")
    assert (loaded.rules, loaded.tool_notes, loaded.episodes) == ([], [], [])


def test_mark_demoted_rewrites_only_the_named_rules(tmp_path):
    pkg = tmp_path / "v0"
    (pkg / "memory").mkdir(parents=True)
    path = pkg / "memory" / "rules.jsonl"
    path.write_text(
        "\n".join(json.dumps(rule(rid, "x", ["k"])) for rid in ("r1", "r2")) + "\n",
        encoding="utf-8",
    )
    mem.mark_demoted_on_disk(pkg, ["r2"])
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[0].get("demoted") is not True
    assert rows[1]["demoted"] is True


# -- hits / misses / demotion ------------------------------------------


def test_usage_is_derived_from_case_results_across_all_runs():
    rows = [
        {"rules_injected": ["r1", "r2"], "passed": True},
        {"rules_injected": ["r1"], "passed": False},
        {"rules_injected": ["r2"], "passed": False},
        {"rules_injected": [], "passed": True},
        {"passed": False},
    ]
    usage = mem.usage_from_case_results(rows)
    assert usage["r1"].hits == 1 and usage["r1"].misses == 1
    assert usage["r2"].hits == 1 and usage["r2"].misses == 1
    assert usage["r1"].uses == 2


def test_demotion_needs_at_least_four_uses_and_more_misses_than_hits():
    usage = {
        "few": mem.RuleUsage(hits=0, misses=3),
        "balanced": mem.RuleUsage(hits=2, misses=2),
        "bad": mem.RuleUsage(hits=1, misses=3),
        "good": mem.RuleUsage(hits=4, misses=1),
    }
    candidates = mem.demotion_candidates(usage, already_demoted=set(), min_uses=4)
    assert [c.entry_id for c in candidates] == ["bad"]
    assert candidates[0].hits == 1 and candidates[0].misses == 3


def test_already_demoted_rules_are_never_proposed_again():
    usage = {"bad": mem.RuleUsage(hits=1, misses=3)}
    assert mem.demotion_candidates(usage, already_demoted={"bad"}, min_uses=4) == []
