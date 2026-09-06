"""Reflection, failure analysis and the improvement gate (PLAN_ADDENDUM.md
sections B, D, E, K; PLAN.md section 7 W6).

Everything here obeys section 0: pass/fail comes from the grader only, and
the harness-recorded transcript is the only thing an LLM call in this package
is ever shown of "what the agent did". Nothing asks the agent to grade
itself.

Pipeline, one attempt at a time (``improve``)::

    diagnose(agent_id, version)      -> ranked list[Diagnosis] over train failures
    reflect(agent_id, version, group) -> list[Proposal] (called by patch() for lever=memory)
    patch(agent_id, version, diagnosis) -> candidate_version (exactly one lever)
    gate(agent_id, candidate_version) -> accepted: bool

``improve(agent_id, max_attempts=3, issue_id=None)`` loops the above.
"""

from __future__ import annotations

from backend.improver.diagnose import Diagnosis, diagnose
from backend.improver.gate import gate
from backend.improver.improve import AttemptOutcome, ImproveResult, improve
from backend.improver.patch import patch
from backend.improver.reflect import Proposal, reflect

__all__ = [
    "AttemptOutcome",
    "Diagnosis",
    "ImproveResult",
    "Proposal",
    "diagnose",
    "gate",
    "improve",
    "patch",
    "reflect",
]
