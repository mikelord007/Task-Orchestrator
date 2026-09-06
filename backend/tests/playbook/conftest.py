"""Shared fixtures for the playbook tests. No real LLM or network involved."""

from __future__ import annotations

import pytest

from backend import llm as backend_llm
from backend.testing.fake_llm import FakeLLM
from backend.testing.fake_llm import text as llm_text


@pytest.fixture
def make_complete():
    """``make_complete(["response text", ...]) -> (complete_fn, fake)``.

    Mirrors ``backend/tests/architect/conftest.py``: ``complete_fn`` is the
    real ``backend.llm.complete`` with a scripted ``FakeLLM`` behind it, so
    tests exercise the exact code path production uses.
    """

    def _factory(responses: list[str]) -> tuple[object, FakeLLM]:
        fake = FakeLLM([llm_text(r) for r in responses])
        backend_llm.set_client(fake)
        return backend_llm.complete, fake

    yield _factory
    backend_llm.reset_client()
