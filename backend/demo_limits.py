"""Cost and concurrency guardrails for the anonymous public demo.

The browser never receives the backend bearer.  Its trusted server-side proxy
adds ``X-Demo-Client-IP``; only a keyed hash is retained.  A global daily cap
still bounds usage if that header is absent or forged after a bearer leak.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.db import init_db, utcnow
from backend.settings import env, env_int

_TRUE_VALUES = {"1", "true", "yes", "on"}
_workflow_lock = threading.Lock()
_active_workflows = 0


@dataclass
class DemoLimitExceeded(RuntimeError):
    message: str
    retry_after: int = 60

    def __str__(self) -> str:
        return self.message


def enabled() -> bool:
    return env("PUBLIC_DEMO_LIMITS").strip().lower() in _TRUE_VALUES


def _day_start(now: datetime) -> str:
    return (
        now.astimezone(UTC)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _since(now: datetime, seconds: int) -> str:
    return (
        (now.astimezone(UTC) - timedelta(seconds=seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def hash_client(client_address: str) -> str:
    """Return a stable, non-reversible identifier without retaining an IP."""
    secret = env("API_AUTH_TOKEN")
    if not secret:
        raise RuntimeError("PUBLIC_DEMO_LIMITS requires API_AUTH_TOKEN")
    normalized = client_address.strip()[:256] or "unknown"
    return hmac.new(secret.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def consume_action(action: str, client_address: str) -> None:
    """Atomically accept one paid workflow or raise before any model call."""
    if not enabled():
        return

    daily_limit = max(1, env_int("DEMO_DAILY_ACTION_LIMIT", 25))
    hourly_limit = max(1, env_int("DEMO_CLIENT_HOURLY_LIMIT", 5))
    cooldown = max(0, env_int("DEMO_CLIENT_COOLDOWN_S", 60))
    now = datetime.now(UTC)
    now_text = utcnow()
    client_hash = hash_client(client_address)

    conn = init_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        global_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM demo_model_actions WHERE ts >= ?", (_day_start(now),)
            ).fetchone()[0]
        )
        if global_count >= daily_limit:
            raise DemoLimitExceeded("public demo daily model-action limit reached", 3600)

        hourly_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM demo_model_actions WHERE client_hash = ? AND ts >= ?",
                (client_hash, _since(now, 3600)),
            ).fetchone()[0]
        )
        if hourly_count >= hourly_limit:
            raise DemoLimitExceeded("public demo hourly model-action limit reached", 3600)

        if cooldown:
            recent = conn.execute(
                "SELECT 1 FROM demo_model_actions WHERE client_hash = ? AND ts >= ? LIMIT 1",
                (client_hash, _since(now, cooldown)),
            ).fetchone()
            if recent is not None:
                raise DemoLimitExceeded("public demo model-action cooldown is active", cooldown)

        conn.execute(
            "INSERT INTO demo_model_actions (ts, client_hash, action) VALUES (?, ?, ?)",
            (now_text, client_hash, action),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_token_budget() -> None:
    if not enabled():
        return
    limit = max(1, env_int("DEMO_DAILY_TOKEN_LIMIT", 250_000))
    conn = init_db()
    try:
        since = _day_start(datetime.now(UTC))
        used = int(
            conn.execute(
                "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) "
                "FROM demo_model_usage WHERE ts >= ?",
                (since,),
            ).fetchone()[0]
        )
        reserved = int(
            conn.execute(
                "SELECT COALESCE(SUM(reserved_tokens), 0) "
                "FROM demo_model_token_reservations WHERE ts >= ?",
                (since,),
            ).fetchone()[0]
        )
    finally:
        conn.close()
    if used + reserved >= limit:
        raise DemoLimitExceeded("public demo daily token limit reached", 3600)


def reserve_token_budget(maximum_tokens: int) -> str | None:
    """Atomically reserve one call's conservative maximum token usage."""
    if not enabled():
        return None
    if maximum_tokens <= 0:
        raise DemoLimitExceeded("public demo requires a bounded model token limit", 3600)

    limit = max(1, env_int("DEMO_DAILY_TOKEN_LIMIT", 250_000))
    now = datetime.now(UTC)
    reservation_id = f"tok_{uuid.uuid4().hex}"
    conn = init_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        since = _day_start(now)
        used = int(
            conn.execute(
                "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) "
                "FROM demo_model_usage WHERE ts >= ?",
                (since,),
            ).fetchone()[0]
        )
        reserved = int(
            conn.execute(
                "SELECT COALESCE(SUM(reserved_tokens), 0) "
                "FROM demo_model_token_reservations WHERE ts >= ?",
                (since,),
            ).fetchone()[0]
        )
        if used + reserved + maximum_tokens > limit:
            raise DemoLimitExceeded("public demo daily token limit reached", 3600)
        conn.execute(
            "INSERT INTO demo_model_token_reservations "
            "(reservation_id, ts, reserved_tokens) VALUES (?, ?, ?)",
            (reservation_id, utcnow(), maximum_tokens),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return reservation_id


def release_token_reservation(reservation_id: str | None) -> None:
    if reservation_id is None:
        return
    conn = init_db()
    try:
        with conn:
            conn.execute(
                "DELETE FROM demo_model_token_reservations WHERE reservation_id = ?",
                (reservation_id,),
            )
    finally:
        conn.close()


def record_usage(
    model: str,
    tokens_in: int,
    tokens_out: int,
    *,
    reservation_id: str | None = None,
) -> None:
    if not enabled():
        return
    if tokens_in < 0 or tokens_out < 0:
        raise RuntimeError("provider returned negative token usage")
    conn = init_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if reservation_id is not None:
            cursor = conn.execute(
                "DELETE FROM demo_model_token_reservations WHERE reservation_id = ?",
                (reservation_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("model token reservation is missing")
        conn.execute(
            "INSERT INTO demo_model_usage (ts, model, tokens_in, tokens_out) VALUES (?, ?, ?, ?)",
            (utcnow(), model, tokens_in, tokens_out),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class WorkflowSlot:
    def __init__(self, claimed: bool) -> None:
        self._claimed = claimed

    def release(self) -> None:
        global _active_workflows
        if not self._claimed:
            return
        with _workflow_lock:
            _active_workflows -= 1
        self._claimed = False

    def __enter__(self) -> WorkflowSlot:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()


def claim_workflow_slot() -> WorkflowSlot:
    """Claim a process-wide workflow slot without building an unbounded queue."""
    global _active_workflows
    if not enabled():
        return WorkflowSlot(False)
    limit = max(1, env_int("DEMO_WORKFLOW_CONCURRENCY", 1))
    with _workflow_lock:
        if _active_workflows >= limit:
            raise DemoLimitExceeded("another public demo model workflow is active", 30)
        _active_workflows += 1
    return WorkflowSlot(True)
