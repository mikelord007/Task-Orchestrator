"""`POST /agents/{id}/improve` (`contracts/api.md`).

Async, per the API conventions: returns `{job_id}` immediately, progress and
the final `ImproveResult` are polled from `GET /jobs/{job_id}` (W2's
`backend/runtime/jobs.py`, reused here rather than duplicated).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.improver.improve import improve
from backend.ledger.query import agent_row
from backend.runtime.jobs import JobStore, default_store, run_in_background

router = APIRouter(tags=["improver"])


class ImproveRequest(BaseModel):
    max_attempts: int = 3
    issue_id: str | None = None


def start_improve(
    agent_id: str,
    max_attempts: int = 3,
    issue_id: str | None = None,
    *,
    store: JobStore | None = None,
) -> str:
    """Validate the agent exists, then run `improve` on a background thread.

    Returns the job id immediately (`POST /agents/{id}/improve` -> `{job_id}`).
    """
    from backend.db import init_db

    conn = init_db()
    try:
        row = agent_row(conn, agent_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown agent_id {agent_id!r}")

    store = store or default_store

    def work(progress):
        result = improve(agent_id, max_attempts=max_attempts, issue_id=issue_id, progress=progress)
        return result.payload()

    return run_in_background(store, "improve", agent_id, work)


@router.post("/agents/{agent_id}/improve")
def post_improve(agent_id: str, body: ImproveRequest) -> dict[str, str]:
    job_id = start_improve(agent_id, max_attempts=body.max_attempts, issue_id=body.issue_id)
    return {"job_id": job_id}
