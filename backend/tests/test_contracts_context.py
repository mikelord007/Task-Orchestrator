from __future__ import annotations

import asyncio

from contracts.context import case_scope, current_case

CASE = {"id": "issue_412", "input": {"number": 412}, "expected": {"labels": ["bug"]}}


def test_defaults_to_none_outside_a_case():
    assert current_case.get() is None


def test_case_scope_sets_and_restores():
    with case_scope(CASE):
        assert current_case.get() == CASE
    assert current_case.get() is None


def test_case_scope_restores_after_an_exception():
    try:
        with case_scope(CASE):
            raise RuntimeError("tool blew up")
    except RuntimeError:
        pass
    assert current_case.get() is None


def test_nested_scopes_restore_the_outer_case():
    outer = {"id": "a"}
    inner = {"id": "b"}
    with case_scope(outer):
        with case_scope(inner):
            assert current_case.get() == inner
        assert current_case.get() == outer


def test_each_concurrent_task_sees_its_own_case():
    """The eval harness runs EVAL_CONCURRENCY cases at once; they must not bleed."""

    async def run_case(case_id: str) -> str:
        with case_scope({"id": case_id}):
            await asyncio.sleep(0)  # yield to the other tasks mid-case
            got = current_case.get()
            assert got is not None
            return got["id"]

    async def main() -> list[str]:
        return await asyncio.gather(*(run_case(f"c{i}") for i in range(8)))

    assert asyncio.run(main()) == [f"c{i}" for i in range(8)]
