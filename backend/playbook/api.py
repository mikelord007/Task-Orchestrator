"""HTTP surface for the playbook (contracts/api.md, contracts/playbook.md rule 5).

``GET /playbook``. Auto-discovered by ``backend.app.discover_routers``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from backend.architect.playbook_reader import read_lessons
from backend.db import REPO_ROOT
from backend.settings import env

router = APIRouter(tags=["playbook"])


def playbook_path() -> Path:
    """``TO_PLAYBOOK_PATH``, defaulting to ``<repo>/playbook/lessons.jsonl``.

    Same env var and default as ``backend.architect.api.playbook_path`` --
    both must resolve to the same file for the ablation and the architect to
    agree on what "the playbook" is.
    """
    return Path(env("TO_PLAYBOOK_PATH") or REPO_ROOT / "playbook" / "lessons.jsonl")


@router.get("/playbook")
def get_playbook() -> list[dict]:
    """Every lesson, parsed as-is (contracts/playbook.md rule 5)."""
    return read_lessons(playbook_path())
