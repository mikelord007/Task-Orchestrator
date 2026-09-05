"""Orchestration modes.

``single`` and ``planner_worker`` (``generate_critic`` is dropped per PLAN.md
section 0.4). Both are thin wrappers over the one loop in ``loop.py``; the only
difference is how many calls happen and what goes into the system prompt.

The model for each step comes from ``agent.yaml.routing`` (``plan``, ``act``),
defaulting to the strong model, so W10 can extend routing without touching the
loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.runtime.config import Knobs
from backend.runtime.drift import DriftWatchdog
from backend.runtime.loop import CompleteFn, DriftSink, LoopResult, run_loop
from backend.runtime.package import LoadedPackage
from backend.runtime.transcript import Transcript

ORCHESTRATION_MODES = ("single", "planner_worker")

PLANNER_INSTRUCTION = (
    "You are the planning step. Do not answer the task and do not call tools. "
    "Write a numbered plan of at most 5 short steps describing which tools to "
    "call and in what order to produce the required output."
)
PLAN_BLOCK_START = "=== PLAN (produced by this agent's planning step) ==="
PLAN_BLOCK_END = "=== END PLAN ==="


@dataclass
class ModeContext:
    package: LoadedPackage
    transcript: Transcript
    knobs: Knobs
    watchdog: DriftWatchdog
    complete: CompleteFn
    system_prompt: str
    user_message: str
    model_strong: str
    model_cheap: str
    on_drift: DriftSink | None = None

    def model_for(self, step: str) -> str:
        return self.package.model_for(
            step, strong=self.model_strong, cheap=self.model_cheap
        )

    def messages(self, system_prompt: str) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self.user_message},
        ]


def run_single(ctx: ModeContext) -> LoopResult:
    """One tool-use loop over the agent's own prompt."""
    return run_loop(
        package=ctx.package,
        transcript=ctx.transcript,
        messages=ctx.messages(ctx.system_prompt),
        knobs=ctx.knobs,
        watchdog=ctx.watchdog,
        complete=ctx.complete,
        model=ctx.model_for("act"),
        on_drift=ctx.on_drift,
        phase="act",
    )


def run_planner_worker(ctx: ModeContext) -> LoopResult:
    """One planning call (no tools), then the worker loop with the plan injected."""
    plan_prompt = f"{ctx.system_prompt.rstrip()}\n\n{PLANNER_INSTRUCTION}\n"
    plan = run_loop(
        package=ctx.package,
        transcript=ctx.transcript,
        messages=ctx.messages(plan_prompt),
        knobs=ctx.knobs,
        watchdog=ctx.watchdog,
        complete=ctx.complete,
        model=ctx.model_for("plan"),
        on_drift=ctx.on_drift,
        use_tools=False,
        phase="plan",
    )
    if plan.aborted:
        return plan
    plan_text = (plan.final_text or "").strip()
    ctx.transcript.record_note("plan produced by the planning step", plan=plan_text)
    worker_prompt = ctx.system_prompt
    if plan_text:
        worker_prompt = f"{ctx.system_prompt.rstrip()}\n\n{PLAN_BLOCK_START}\n{plan_text}\n{PLAN_BLOCK_END}\n"
    result = run_loop(
        package=ctx.package,
        transcript=ctx.transcript,
        messages=ctx.messages(worker_prompt),
        knobs=ctx.knobs,
        watchdog=ctx.watchdog,
        complete=ctx.complete,
        model=ctx.model_for("act"),
        on_drift=ctx.on_drift,
        phase="act",
    )
    result.nudged = result.nudged or plan.nudged
    return result


MODES = {"single": run_single, "planner_worker": run_planner_worker}


def run_mode(mode: str, ctx: ModeContext) -> LoopResult:
    """Dispatch to an orchestration mode, defaulting to ``single``."""
    return MODES.get(str(mode or "single"), run_single)(ctx)
