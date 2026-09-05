"""Shared fixtures for the architect tests. No real LLM or network involved."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TEST_DIR.parents[1]
REPO_ROOT = BACKEND_DIR.parent
for _path in (str(TEST_DIR), str(BACKEND_DIR), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture
def evaluator_dir(tmp_path):
    """A tiny evaluator fixture: README.md + cases.jsonl with train/holdout rows."""
    base = tmp_path / "evaluators" / "widget_triage"
    base.mkdir(parents=True)
    (base / "README.md").write_text(
        "# widget_triage\n\nGiven an issue, decide its labels and component.\n",
        encoding="utf-8",
    )
    rows = [
        {
            "id": "c1",
            "split": "train",
            "input": {"issue_number": 1},
            "expected": {"labels": ["bug"], "component": "terminal"},
            "tags": [],
        },
        {
            "id": "c2",
            "split": "train",
            "input": {"issue_number": 2},
            "expected": {"labels": ["docs"], "component": "docs", "priority": "p2"},
            "tags": [],
        },
        {
            "id": "c3",
            "split": "holdout",
            "input": {"issue_number": 3},
            "expected": {"labels": [], "component": "docs"},
            "tags": [],
        },
    ]
    (base / "cases.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return tmp_path / "evaluators"
