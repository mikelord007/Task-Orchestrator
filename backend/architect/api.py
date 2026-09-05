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

from .evaluators import list_evaluators
from .generate import generate

router = APIRouter(tags=["architect"])

EVALUATORS_ROOT = REPO_ROOT / "evaluators"
AGENTS_ROOT = REPO_ROOT / "agents"
PLAYBOOK_PATH = REPO_ROOT / "playbook" / "lessons.jsonl"


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
    """agent.yaml + prompt + tool names + memory entries for one version."""
    from contracts.agent import PackageError, load_package

    try:
        pkg = load_package(package_dir)
    except PackageError as exc:
        raise HTTPException(
            status_code=500, detail=f"stored package at {package_dir} is invalid: {exc.errors}"
        ) from exc

    view = {
        "agent_yaml": pkg.config.model_dump(),
        "prompt": pkg.prompt,
        "tools": sorted(pkg.tools),
        "memory": {
            "rules": [rule.model_dump() for rule in pkg.memory.rules],
            "tool_notes": [note.model_dump() for note in pkg.memory.tool_notes],
            "episodes": [episode.model_dump() for episode in pkg.memory.episodes],
        },
    }
    orchestration_doc = package_dir / "ORCHESTRATION.md"
    if orchestration_doc.is_file():
        view["orchestration_notes"] = orchestration_doc.read_text(encoding="utf-8")
    return view


@router.post("/agents")
def create_agent(body: CreateAgentRequest) -> dict:
    result = generate(
        goal=body.goal,
        domain=body.domain,
        tools=body.tools,
        evaluator_id=body.evaluator_id,
        use_playbook=body.use_playbook,
        agents_root=AGENTS_ROOT,
        evaluators_root=EVALUATORS_ROOT,
        playbook_path=PLAYBOOK_PATH,
    )
    return {"agent_id": result.agent_id, "version": result.version}


@router.get("/agents")
def list_agents() -> list[dict]:
    conn = init_db()
    try:
        rows = conn.execute("SELECT * FROM agents ORDER BY created_ts DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str) -> dict:
    conn = init_db()
    try:
        row = _agent_row(conn, agent_id)
    finally:
        conn.close()
    package_dir = AGENTS_ROOT / agent_id / f"v{row['current_version']}"
    return {**row, **_package_view(package_dir)}


@router.get("/agents/{agent_id}/versions/{version}")
def get_agent_version(agent_id: str, version: int) -> dict:
    conn = init_db()
    try:
        row = _agent_row(conn, agent_id)
    finally:
        conn.close()
    package_dir = AGENTS_ROOT / agent_id / f"v{version}"
    if not package_dir.is_dir():
        raise HTTPException(
            status_code=404, detail=f"agent {agent_id!r} has no version {version}"
        )
    changes_path = package_dir / "CHANGES.diff"
    return {
        **row,
        "version": version,
        **_package_view(package_dir),
        "changes_diff": changes_path.read_text(encoding="utf-8") if changes_path.is_file() else None,
    }


@router.get("/evaluators")
def get_evaluators() -> list[dict]:
    return list_evaluators(EVALUATORS_ROOT)
