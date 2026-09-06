"""HTTP surface for the architect (contracts/api.md).

`POST /agents`, `GET /agents`, `GET /agents/{id}`,
`GET /agents/{id}/versions/{n}`, `GET /evaluators`. Auto-discovered by
`backend.app.discover_routers` -- no manual registration.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import REPO_ROOT, init_db
from backend.settings import env

from .evaluator_reader import EvaluatorNotFoundError
from .evaluators import list_evaluators
from .generate import generate
from .inspect_package import PackageReadError, read_package_view
from .steps import ArchitectStepError

router = APIRouter(tags=["architect"])


def agents_root() -> Path:
    """`TO_AGENTS_ROOT`, defaulting to `<repo>/agents`. Read fresh every call
    (see `backend.settings`) so tests can `monkeypatch.setenv` a tmp_path."""
    return Path(env("TO_AGENTS_ROOT") or REPO_ROOT / "agents")


def evaluators_root() -> Path:
    """`TO_EVALUATORS_ROOT`, defaulting to `<repo>/evaluators`."""
    return Path(env("TO_EVALUATORS_ROOT") or REPO_ROOT / "evaluators")


def playbook_path() -> Path:
    """`TO_PLAYBOOK_PATH`, defaulting to `<repo>/playbook/lessons.jsonl`."""
    return Path(env("TO_PLAYBOOK_PATH") or REPO_ROOT / "playbook" / "lessons.jsonl")


class CreateAgentRequest(BaseModel):
    goal: str
    domain: str
    tools: list[str] = Field(default_factory=list)
    evaluator_id: str
    use_playbook: bool = False


def _agent_row(conn, agent_id: str) -> dict:
    row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id!r} not found")
    return dict(row)


def _package_view(package_dir: Path) -> dict:
    """agent.yaml + prompt + tool specs + memory entries for one version.

    Reads structurally (``inspect_package.read_package_view``), never by
    importing the package -- a stored package can contain an LLM-authored
    glue tool (``ARCHITECT_ALLOW_GLUE_TOOLS``), and this endpoint must not
    execute it just because someone looked the agent up.
    """
    try:
        return read_package_view(package_dir)
    except PackageReadError as exc:
        raise HTTPException(
            status_code=500, detail=f"stored package at {package_dir} is invalid: {exc.errors}"
        ) from exc


def _latest_pass_stats(conn) -> dict[tuple[str, int, str], dict]:
    """Read each current agent version's newest finished split in one query."""
    rows = conn.execute(
        """
        WITH ranked AS (
          SELECT e.agent_id,
                 e.agent_version,
                 json_extract(e.payload, '$.split') AS split,
                 json_extract(e.payload, '$.pass_at_1') AS mean,
                 json_extract(e.payload, '$.pass_rate_std') AS std,
                 json_extract(e.payload, '$.pass_rate_min') AS minimum,
                 json_extract(e.payload, '$.pass_rate_max') AS maximum,
                 ROW_NUMBER() OVER (
                   PARTITION BY e.agent_id,
                                e.agent_version,
                                json_extract(e.payload, '$.split')
                   ORDER BY e.id DESC
                 ) AS recency
          FROM events AS e
          JOIN agents AS a
            ON a.agent_id = e.agent_id
           AND a.current_version = e.agent_version
          WHERE e.kind = 'run_finished'
            AND json_extract(e.payload, '$.split') IN ('train', 'holdout')
        )
        SELECT agent_id, agent_version, split, mean, std, minimum, maximum
        FROM ranked
        WHERE recency = 1
        """
    ).fetchall()
    return {
        (row["agent_id"], row["agent_version"], row["split"]): {
            "mean": row["mean"],
            "std": row["std"],
            "min": row["minimum"],
            "max": row["maximum"],
        }
        for row in rows
    }


def _agent_summary(row, latest_stats: dict[tuple[str, int, str], dict]) -> dict:
    summary = dict(row)
    summary["name"] = " ".join(summary["goal"].split()[:6]) or summary["agent_id"]
    for split in ("train", "holdout"):
        summary[f"latest_{split}"] = latest_stats.get(
            (summary["agent_id"], summary["current_version"], split)
        )
    return summary


@router.post("/agents")
def create_agent(body: CreateAgentRequest) -> dict:
    try:
        result = generate(
            goal=body.goal,
            domain=body.domain,
            tools=body.tools,
            evaluator_id=body.evaluator_id,
            use_playbook=body.use_playbook,
            agents_root=agents_root(),
            evaluators_root=evaluators_root(),
            playbook_path=playbook_path(),
        )
    except EvaluatorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ArchitectStepError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"agent_id": result.agent_id, "version": result.version}


@router.get("/agents")
def list_agents() -> list[dict]:
    conn = init_db()
    try:
        # created_ts has second resolution, so two agents created within the
        # same second tie -- rowid (insertion order) breaks the tie.
        rows = conn.execute("SELECT * FROM agents ORDER BY created_ts DESC, rowid DESC").fetchall()
        latest_stats = _latest_pass_stats(conn)
        return [_agent_summary(row, latest_stats) for row in rows]
    finally:
        conn.close()


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str) -> dict:
    conn = init_db()
    try:
        row = _agent_row(conn, agent_id)
    finally:
        conn.close()
    package_dir = agents_root() / agent_id / f"v{row['current_version']}"
    return {**row, **_package_view(package_dir)}


@router.get("/agents/{agent_id}/versions/{version}")
def get_agent_version(agent_id: str, version: int) -> dict:
    conn = init_db()
    try:
        row = _agent_row(conn, agent_id)
    finally:
        conn.close()
    package_dir = agents_root() / agent_id / f"v{version}"
    if not package_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"agent {agent_id!r} has no version {version}")
    changes_path = package_dir / "CHANGES.diff"
    return {
        **row,
        "version": version,
        **_package_view(package_dir),
        "changes_diff": changes_path.read_text(encoding="utf-8")
        if changes_path.is_file()
        else None,
    }


@router.get("/evaluators")
def get_evaluators() -> list[dict]:
    return list_evaluators(evaluators_root())
