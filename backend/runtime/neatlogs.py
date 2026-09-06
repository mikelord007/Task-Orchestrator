"""Safe, optional Neatlogs tracing for the runtime.

Export is deliberately double opt-in: both ``NEATLOGS_ENABLED=true`` and a
``NEATLOGS_API_KEY`` are required. A key in a developer's ``.env`` therefore
cannot make tests or local startup upload telemetry by accident.

The adapter owns SDK lifecycle and failure isolation. Business code executes
exactly once even when creating or closing a telemetry span fails.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import Context, ContextVar, copy_context
from dataclasses import dataclass
from itertools import islice
from typing import Any

from backend.settings import env, env_float, env_int

log = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_CONTENT_OMITTED = "[content omitted]"
_REDACTED = "[redacted]"
_MAX_CONTENT_CHARS = 2_048
_MAX_COLLECTION_ITEMS = 50
_WARNING_INTERVAL_S = 60.0
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|password|secret|"
    r"token(?![_-](?:count|usage))|cookie)",
    re.I,
)
_CONTENT_KEY = re.compile(
    r"(?:^|\.)(?:content|input\.value|output\.value|arguments|result|error\.message|"
    r"exception\.(?:message|stacktrace)|(?:system_|user_)?prompt(?:_template)?)$",
    re.I,
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .()\-]{7,}\d)(?!\w)")
_CREDENTIAL = re.compile(r"(?i)(?:bearer\s+\S+|(?:sk|ghp|github_pat|xox[baprs])-[_A-Za-z0-9-]{8,})")

_state_lock = threading.RLock()
_initialized = False
_active = False
_shutdown_started = False
_span_depth: ContextVar[int] = ContextVar("task_orchestrator_neatlogs_depth", default=0)
_last_warning: dict[str, float] = {}

_OTEL_SPAN_LIMITS = {
    "OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT": 128,
    "OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT": _MAX_CONTENT_CHARS,
    "OTEL_SPAN_EVENT_COUNT_LIMIT": 32,
    "OTEL_EVENT_ATTRIBUTE_COUNT_LIMIT": 64,
    "OTEL_SPAN_LINK_COUNT_LIMIT": 32,
    "OTEL_LINK_ATTRIBUTE_COUNT_LIMIT": 32,
}


@dataclass
class Trace:
    """Trace details available without changing the persisted API contract."""

    trace_id: str | None = None
    # Neatlogs does not document a dashboard URL constructor. Keep the existing
    # optional contract empty rather than manufacturing a link.
    url: str | None = None


def _requested() -> bool:
    return env("NEATLOGS_ENABLED").strip().lower() in _TRUE_VALUES


def enabled() -> bool:
    """Whether tracing initialized successfully for this process."""
    with _state_lock:
        return _active


def _warn(operation: str, exc: BaseException | None = None) -> None:
    """Emit a bounded, rate-limited warning without exception text or secrets."""
    now = time.monotonic()
    with _state_lock:
        if now - _last_warning.get(operation, -_WARNING_INTERVAL_S) < _WARNING_INTERVAL_S:
            return
        if len(_last_warning) >= 32 and operation not in _last_warning:
            oldest = min(_last_warning, key=_last_warning.get)
            _last_warning.pop(oldest, None)
        _last_warning[operation] = now
    suffix = f" ({type(exc).__name__})" if exc is not None else ""
    log.warning("Neatlogs %s failed; telemetry was skipped%s", operation, suffix)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(max(env_int(name, default), minimum), maximum)
    except ValueError as exc:
        _warn(f"configuration for {name}", exc)
        return default


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        return min(max(env_float(name, default), minimum), maximum)
    except ValueError as exc:
        _warn(f"configuration for {name}", exc)
        return default


@contextmanager
def _bounded_otel_span_limits() -> Iterator[None]:
    """Apply conservative limits while the SDK constructs its private provider."""
    previous = {name: os.environ.get(name) for name in _OTEL_SPAN_LIMITS}
    try:
        for name, maximum in _OTEL_SPAN_LIMITS.items():
            try:
                configured = int(previous[name]) if previous[name] is not None else maximum
            except ValueError:
                configured = maximum
            os.environ[name] = str(min(maximum, max(1, configured)))
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def initialize(*, tracer_provider: Any | None = None, disable_export: bool = False) -> bool:
    """Initialize the documented SDK once after environment loading.

    ``tracer_provider`` and ``disable_export`` support network-free SDK tests;
    normal application startup leaves both at their defaults.
    """
    global _active, _initialized, _shutdown_started
    with _state_lock:
        if _initialized:
            return _active
        _initialized = True
        _shutdown_started = False

        if not _requested():
            return False
        api_key = env("NEATLOGS_API_KEY").strip()
        if not api_key and not disable_export:
            _warn("initialization (NEATLOGS_API_KEY is not configured)")
            return False

        try:
            import neatlogs as sdk

            with _bounded_otel_span_limits():
                sdk.init(
                    api_key=api_key or None,
                    workflow_name="task-orchestrator",
                    tags=["backend"],
                    sample_rate=_bounded_float("NEATLOGS_SAMPLE_RATE", 1.0, 0.0, 1.0),
                    batch_size=_bounded_int("NEATLOGS_BATCH_SIZE", 32, 1, 100),
                    flush_interval=_bounded_float(
                        "NEATLOGS_FLUSH_INTERVAL_S", 10.0, 1.0, 60.0
                    ),
                    mask=telemetry_mask,
                    capture_logs=False,
                    register_shutdown_handlers=False,
                    uploads_enabled=False,
                    tracer_provider=tracer_provider,
                    disable_export=disable_export,
                )
        except Exception as exc:  # noqa: BLE001 - tracing is never business-critical
            _warn("initialization", exc)
            return False
        _active = True
        return True


def shutdown() -> bool:
    """Flush and shut down once, under a small process-wide time budget."""
    global _active, _shutdown_started
    with _state_lock:
        if not _active or _shutdown_started:
            return True
        _shutdown_started = True
        _active = False

    timeout_ms = _bounded_int("NEATLOGS_SHUTDOWN_TIMEOUT_MS", 2_000, 100, 5_000)
    started = time.monotonic()
    try:
        import neatlogs as sdk
    except Exception as exc:  # noqa: BLE001 - shutdown must not break app teardown
        _warn("shutdown import", exc)
        return False

    flush_budget = max(1, timeout_ms // 2)
    try:
        flush_ok = bool(sdk.flush(timeout_millis=flush_budget))
    except Exception as exc:  # noqa: BLE001 - shutdown still needs to run
        _warn("flush", exc)
        flush_ok = False
    elapsed_ms = int((time.monotonic() - started) * 1_000)
    remaining_ms = max(1, timeout_ms - max(flush_budget, elapsed_ms))
    try:
        shutdown_ok = bool(sdk.shutdown(timeout_millis=remaining_ms))
    except Exception as exc:  # noqa: BLE001 - shutdown must not break app teardown
        _warn("shutdown", exc)
        shutdown_ok = False
    return flush_ok and shutdown_ok


def safe_identifier(value: Any, namespace: str) -> str:
    """Return a stable, non-reversible identifier suitable for telemetry."""
    digest = hashlib.sha256(f"{namespace}\0{value}".encode("utf-8", "replace")).hexdigest()[:16]
    return f"{namespace}_{digest}"


def safe_metadata(**values: Any) -> dict[str, str | int | float | bool]:
    """Allow only bounded scalars under the application's telemetry namespace."""
    result: dict[str, str | int | float | bool] = {}
    for key, value in values.items():
        if value is None:
            continue
        attr = f"task_orchestrator.{key}"
        if isinstance(value, (bool, int, float)):
            result[attr] = value
        else:
            result[attr] = str(value)[:256]
    return result


def _redact_text(value: str) -> str:
    value = _CREDENTIAL.sub(_REDACTED, value)
    value = _EMAIL.sub(_REDACTED, value)
    value = _PHONE.sub(_REDACTED, value)
    if len(value) > _MAX_CONTENT_CHARS:
        return value[: _MAX_CONTENT_CHARS - 16] + "...[truncated]"
    return value


def _sanitize(value: Any, *, key: str = "", capture_content: bool) -> Any:
    if _SENSITIVE_KEY.search(key):
        return _REDACTED
    if (
        _CONTENT_KEY.search(key)
        and not capture_content
        and not isinstance(value, (bool, int, float, type(None)))
    ):
        return _CONTENT_OMITTED
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(child_key)[:128]: _sanitize(
                child_value,
                key=f"{key}.{child_key}" if key else str(child_key),
                capture_content=capture_content,
            )
            for child_key, child_value in islice(value.items(), _MAX_COLLECTION_ITEMS)
        }
    if isinstance(value, (list, tuple)):
        return [
            _sanitize(item, key=key, capture_content=capture_content)
            for item in value[:_MAX_COLLECTION_ITEMS]
        ]
    return value


def telemetry_mask(item: dict[str, Any], *, context: Any = None) -> dict[str, Any]:
    """Redact and bound the SDK's canonical telemetry snapshot before export."""
    del context
    capture_content = env("NEATLOGS_CAPTURE_CONTENT").strip().lower() in _TRUE_VALUES
    sanitized = _sanitize(item, capture_content=capture_content)
    return sanitized if isinstance(sanitized, dict) else {}


def _trace_id(handle: Any) -> str | None:
    try:
        context = handle.get_span_context()
        trace_id = int(context.trace_id)
        return f"{trace_id:032x}" if trace_id else None
    except Exception:  # noqa: BLE001 - optional correlation only
        return None


@contextmanager
def span(name: str, *, kind: str = "CHAIN", **metadata: Any) -> Iterator[Trace]:
    """Open one documented ``neatlogs.trace`` span, or safely no-op."""
    result = Trace()
    if not enabled():
        yield result
        return

    manager: Any = None
    token: Any = None
    exc_info: tuple[Any, Any, Any] = (None, None, None)
    try:
        import neatlogs as sdk

        attributes = safe_metadata(**metadata)
        tool_name = metadata.get("tool_name")
        if kind == "TOOL" and tool_name is not None:
            attributes["neatlogs.tool.name"] = str(tool_name)[:256]
        manager = sdk.trace(name, kind=kind, **attributes)
        handle = manager.__enter__()
        result.trace_id = _trace_id(handle)
        token = _span_depth.set(_span_depth.get() + 1)
    except Exception as exc:  # noqa: BLE001 - run without telemetry on enter failure
        manager = None
        _warn(f"span start for {name}", exc)

    try:
        yield result
    except BaseException:  # preserve the business exception, regardless of SDK behavior
        import sys

        exc_info = sys.exc_info()
        raise
    finally:
        if token is not None:
            _span_depth.reset(token)
        if manager is not None:
            try:
                manager.__exit__(*exc_info)
            except Exception as exc:  # noqa: BLE001 - telemetry cannot alter outcomes
                _warn(f"span finish for {name}", exc)


@contextmanager
def workflow_span(name: str, **metadata: Any) -> Iterator[Trace]:
    """Create a root WORKFLOW, or a CHAIN when already inside our workflow."""
    kind = "WORKFLOW" if _span_depth.get() == 0 else "CHAIN"
    with span(name, kind=kind, **metadata) as trace:
        yield trace


def trace_case(name: str = "task_orchestrator.case", **metadata: Any) -> Iterator[Trace]:
    """Backward-compatible case context using a low-cardinality AGENT span."""
    del name
    return span("task_orchestrator.case", kind="AGENT", **metadata)


def copy_current_context() -> Context:
    """Capture Neatlogs and application contextvars for a worker thread."""
    return copy_context()


def wrap_client(client: Any) -> Any:
    """Wrap one real provider client once; injected fakes never call this path."""
    if not enabled() or getattr(client, "_task_orchestrator_neatlogs_wrapped", False):
        return client
    try:
        import neatlogs as sdk

        wrapped = sdk.wrap(client, component="llm")
        wrapped._task_orchestrator_neatlogs_wrapped = True
        return wrapped
    except Exception as exc:  # noqa: BLE001 - retain the original usable client
        _warn("client wrapping", exc)
        return client


def _reset_for_tests() -> None:
    """Reset adapter state after a test-owned SDK shutdown."""
    global _active, _initialized, _shutdown_started
    with _state_lock:
        _active = False
        _initialized = False
        _shutdown_started = False
        _last_warning.clear()
