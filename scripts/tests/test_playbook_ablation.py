"""``scripts/playbook_ablation.py`` end to end with FakeLLM and a stub `run_eval`.

`run_eval` (W2's eval harness) is not merged yet -- the stub here plays its
part exactly as far as this script cares: it writes `run_started`,
`case_result` and `run_finished` events for `(agent_id, version, split)` so
`backend.ledger.metrics.pass_at_1`/`pass_pow_k` have something real to read
back, mirroring how the real harness would populate the ledger.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from backend import llm as backend_llm
from backend.ledger.emit import emit
from backend.testing.fake_llm import FakeLLM
from backend.testing.fake_llm import text as llm_text

REPO_ROOT = Path(__file__).resolve().parents[2]

TASK_IDS = ["t1", "t2", "t3"]


def _load_ablation_module():
    """`scripts/` has no `__init__.py` (matches every other script test in
    this directory), so load the module by path rather than a package import."""
    spec = importlib.util.spec_from_file_location(
        "playbook_ablation", REPO_ROOT / "scripts" / "playbook_ablation.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


run_ablation = _load_ablation_module().run_ablation


@pytest.fixture
def make_complete():
    def _factory(responses: list[str]) -> tuple[object, FakeLLM]:
        fake = FakeLLM([llm_text(r) for r in responses])
        backend_llm.set_client(fake)
        return backend_llm.complete, fake

    yield _factory
    backend_llm.reset_client()


def _stub_run_eval(conn):
    """First call scores worse (playbook off), second scores better (on)."""
    calls: list[str] = []

    def run_eval(agent_id: str, version: int, split: str, trials: int):
        good = len(calls) == 1  # off is called first by run_ablation, then on
        calls.append(agent_id)
        run_id = f"run_{agent_id}"

        emit(
            "run_started",
            agent_id=agent_id,
            agent_version=version,
            run_id=run_id,
            conn=conn,
            split=split,
            case_count=len(TASK_IDS),
            trials=trials,
        )
        per_trial_rates: list[float] = []
        for trial in range(trials):
            passed_count = 0
            for i, task_id in enumerate(TASK_IDS):
                passed = True if good else i == 0
                passed_count += int(passed)
                emit(
                    "case_result",
                    agent_id=agent_id,
                    agent_version=version,
                    run_id=run_id,
                    conn=conn,
                    case_id=task_id,
                    trial=trial,
                    passed=passed,
                    score=1.0 if passed else 0.0,
                    tokens_in=100,
                    tokens_out=50,
                    cost_usd=0.001,
                    latency_ms=500,
                    steps=3,
                    transcript_path=f"runs/{run_id}/{task_id}.t{trial}.json",
                    tool_calls=2,
                    tool_errors=0,
                )
            per_trial_rates.append(passed_count / len(TASK_IDS))
        stable = sum(1 for t in TASK_IDS if True) if good else 1
        emit(
            "run_finished",
            agent_id=agent_id,
            agent_version=version,
            run_id=run_id,
            conn=conn,
            split=split,
            trials=trials,
            pass_at_1=sum(per_trial_rates) / trials,
            pass_pow_k=stable / len(TASK_IDS),
            pass_rate_std=0.0,
            pass_rate_min=min(per_trial_rates),
            pass_rate_max=max(per_trial_rates),
            total_cost_usd=0.003 * trials,
            p50_latency_ms=500,
            p95_latency_ms=500,
            drift_count=0,
            tokens_saved_by_drift=0,
        )
        return {"run_id": run_id}

    return run_eval, calls


def _generate_script(*, use_playbook: bool, applied_lesson_id: str | None = None) -> list[str]:
    responses = [
        json.dumps({"mode": "single", "reason": "One call is enough for this task."}),
        "Answer with a JSON object with keys: category, priority, needs_human.",
        json.dumps({"tools": ["json_validate", "date_parse"], "glue_tool": None}),
    ]
    if use_playbook:
        responses.append(
            json.dumps(
                {
                    "prompt": "Revised prompt. Answer with a JSON object with keys: "
                    "category, priority, needs_human.",
                    "applied_lesson_ids": [applied_lesson_id] if applied_lesson_id else [],
                }
            )
        )
    return responses


def test_run_ablation_produces_the_contract_shape(tmp_path, conn, make_complete):
    playbook_path = tmp_path / "playbook" / "lessons.jsonl"
    playbook_path.parent.mkdir(parents=True)
    playbook_path.write_text(
        json.dumps(
            {
                "id": "lesson_abc123",
                "lever": "memory",
                "trigger": "agent must map free-text input to a fixed label vocabulary",
                "lesson": "Write one rule per label.",
                "domain_tags": ["classification"],
                "source_agent_id": "a_other_domain",
                "source_issue_id": None,
                "ts": "2026-09-06T10:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    scripted = _generate_script(use_playbook=False) + _generate_script(
        use_playbook=True, applied_lesson_id="lesson_abc123"
    )
    complete, fake = make_complete(scripted)
    run_eval, calls = _stub_run_eval(conn)

    report = run_ablation(
        conn=conn,
        trials=2,
        agents_root=tmp_path / "agents",
        evaluators_root=REPO_ROOT / "evaluators",
        playbook_path=playbook_path,
        run_eval=run_eval,
        complete=complete,
        model="strong-model",
    )

    assert report["domain"] == "ticket_triage"
    assert report["trials"] == 2
    assert len(calls) == 2

    for key in ("playbook_off", "playbook_on"):
        assert set(report[key]) == {"pass_at_1", "pass_pow_k", "std"}
        assert report[key]["pass_at_1"] is not None

    # off scores worse than on, per the stub's scripted pattern.
    assert report["playbook_off"]["pass_at_1"] < report["playbook_on"]["pass_at_1"]
    assert report["applied_lesson_ids"] == ["lesson_abc123"]
    assert set(report["agent_ids"]) == {"playbook_off", "playbook_on"}
    assert report["agent_ids"]["playbook_off"] != report["agent_ids"]["playbook_on"]
    assert fake.call_count == len(scripted)


def test_run_ablation_reports_a_flat_result_honestly(tmp_path, conn, make_complete):
    """No lessons in the playbook -> applied_lesson_ids is empty, not fabricated."""
    playbook_path = tmp_path / "playbook" / "lessons.jsonl"
    scripted = _generate_script(use_playbook=False) + _generate_script(use_playbook=True)
    complete, _fake = make_complete(scripted)

    def flat_run_eval(agent_id: str, version: int, split: str, trials: int):
        run_id = f"run_{agent_id}"
        emit(
            "run_started",
            agent_id=agent_id,
            agent_version=version,
            run_id=run_id,
            conn=conn,
            split=split,
            case_count=1,
            trials=trials,
        )
        for trial in range(trials):
            emit(
                "case_result",
                agent_id=agent_id,
                agent_version=version,
                run_id=run_id,
                conn=conn,
                case_id="t1",
                trial=trial,
                passed=False,
                score=0.0,
                tokens_in=10,
                tokens_out=10,
                cost_usd=0.0001,
                latency_ms=100,
                steps=1,
                transcript_path=f"runs/{run_id}/t1.t{trial}.json",
                tool_calls=1,
                tool_errors=0,
            )
        emit(
            "run_finished",
            agent_id=agent_id,
            agent_version=version,
            run_id=run_id,
            conn=conn,
            split=split,
            trials=trials,
            pass_at_1=0.0,
            pass_pow_k=0.0,
            pass_rate_std=0.0,
            pass_rate_min=0.0,
            pass_rate_max=0.0,
            total_cost_usd=0.0002,
            p50_latency_ms=100,
            p95_latency_ms=100,
            drift_count=0,
            tokens_saved_by_drift=0,
        )

    report = run_ablation(
        conn=conn,
        trials=2,
        agents_root=tmp_path / "agents",
        evaluators_root=REPO_ROOT / "evaluators",
        playbook_path=playbook_path,
        run_eval=flat_run_eval,
        complete=complete,
        model="strong-model",
    )

    assert report["playbook_off"]["pass_at_1"] == 0.0
    assert report["playbook_on"]["pass_at_1"] == 0.0
    assert report["applied_lesson_ids"] == []
