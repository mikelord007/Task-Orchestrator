from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.runtime.config import Knobs
from backend.runtime.package import load_from_dir

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
# W2's own drift/memory/loop scenario fixture - not backend/tests/fixtures/toy_agent/v0/,
# which is Phase 0's shared shout-tool fixture used by the contract tests.
TOY_AGENT_V0 = FIXTURES / "toy_triage_agent" / "v0"
TOY_EVALUATOR = FIXTURES / "toy_evaluator"


class RealLedger:
    """The real ``backend.ledger.emit``/``read``, bound to one temp sqlite file
    per test.

    This is deliberately not a hand-rolled test double: routing every write
    through the genuine ``emit()`` means every payload is validated against
    ``contracts/events.py`` for real, in every test - the same "kind"/"lever"
    collision or evidence-shape bug a production caller would hit shows up
    here too.
    """

    def __init__(self, db_path: Path) -> None:
        from backend.db import init_db

        self._db = db_path
        init_db(db_path).close()

    def emit(self, kind: str, /, **fields: Any) -> int:
        from backend.ledger.emit import emit

        return emit(kind, db=self._db, **fields)

    def read(self, agent_id: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        from backend.ledger.emit import read

        return read(agent_id=agent_id, kind=kind, db=self._db)

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return self.read(kind=kind)

    def kinds(self) -> list[str]:
        return [event["kind"] for event in self.read()]


@pytest.fixture
def ledger(tmp_path: Path) -> RealLedger:
    return RealLedger(tmp_path / "ledger_test.sqlite3")


@pytest.fixture
def knobs() -> Knobs:
    return Knobs(
        eval_trials=3,
        eval_concurrency=1,
        drift_max_steps=12,
        drift_token_budget=20_000,
        drift_repeat_call_limit=3,
        case_timeout_s=120,
        memory_top_k=12,
        memory_min_uses=4,
    )


@pytest.fixture
def toy_package_dir(tmp_path: Path) -> Path:
    """A writable copy of the toy package (memory demotion writes to disk)."""
    import shutil

    destination = tmp_path / "agents" / "toy" / "v0"
    shutil.copytree(TOY_AGENT_V0, destination)
    return destination


@pytest.fixture
def toy_package(toy_package_dir: Path):
    return load_from_dir(toy_package_dir, agent_id="toy", version=0)


@pytest.fixture
def evaluator_path() -> Path:
    return TOY_EVALUATOR


@pytest.fixture
def toy_cases() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (TOY_EVALUATOR / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
