from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.runtime.config import Knobs
from backend.runtime.package import load_from_dir

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TOY_AGENT_V0 = FIXTURES / "toy_agent" / "v0"
TOY_EVALUATOR = FIXTURES / "toy_evaluator"


class RecordingLedger:
    """Stand-in for backend/ledger/emit.py: records instead of inserting."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, kind: str, /, **fields: Any) -> int:
        event_id = len(self.events) + 1
        payload = {
            k: v
            for k, v in fields.items()
            if k not in {"agent_id", "agent_version", "run_id", "lever"}
        }
        self.events.append(
            {
                "id": event_id,
                "kind": kind,
                "agent_id": fields.get("agent_id"),
                "agent_version": fields.get("agent_version"),
                "run_id": fields.get("run_id"),
                "lever": fields.get("lever"),
                "payload": payload,
            }
        )
        return event_id

    def read(
        self, agent_id: str | None = None, kind: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            event
            for event in self.events
            if (agent_id is None or event["agent_id"] == agent_id)
            and (kind is None or event["kind"] == kind)
        ]

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["kind"] == kind]

    def kinds(self) -> list[str]:
        return [event["kind"] for event in self.events]


@pytest.fixture
def ledger() -> RecordingLedger:
    return RecordingLedger()


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
        for line in (TOY_EVALUATOR / "cases.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
