"""Shared fixtures for the architect tests. No real LLM or network involved.

``make_complete`` scripts ``backend.testing.fake_llm.FakeLLM`` behind
``backend.llm.complete`` -- the real completion function, with the real client
swapped out -- so every architect test exercises exactly the code path
``backend.architect.generate.generate()`` uses in production.
"""

from __future__ import annotations

import json

import pytest

from backend import llm as backend_llm
from backend.testing.fake_llm import FakeLLM
from backend.testing.fake_llm import text as llm_text


@pytest.fixture
def make_complete():
    """``make_complete(["response text", ...]) -> (complete_fn, fake)``.

    ``complete_fn`` is ``backend.llm.complete`` itself; ``fake`` is the
    injected ``FakeLLM`` for inspecting ``fake.requests`` / ``fake.call_count``.
    The client is reset after the test regardless of outcome.
    """

    def _factory(responses: list[str]) -> tuple[object, FakeLLM]:
        fake = FakeLLM([llm_text(r) for r in responses])
        backend_llm.set_client(fake)
        return backend_llm.complete, fake

    yield _factory
    backend_llm.reset_client()


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
