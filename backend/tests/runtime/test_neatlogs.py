"""Network-free tests for the Neatlogs adapter and real installed SDK."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend import llm
from backend.runtime import neatlogs
from backend.runtime.evaluation import run_eval
from backend.runtime.transcript import Transcript
from backend.testing.fake_llm import FakeLLM, text


@pytest.fixture
def sdk_capture(monkeypatch):
    """A documented private provider with an in-memory, network-free exporter."""
    import neatlogs as sdk

    sdk.shutdown(timeout_millis=100)
    neatlogs._reset_for_tests()
    monkeypatch.setenv("NEATLOGS_ENABLED", "true")
    monkeypatch.setenv("NEATLOGS_API_KEY", "test-only-not-a-real-key")
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    assert neatlogs.initialize(tracer_provider=provider, disable_export=True)
    yield exporter
    neatlogs.shutdown()
    provider.shutdown()
    neatlogs._reset_for_tests()


def test_key_without_explicit_opt_in_is_a_noop(monkeypatch):
    import neatlogs as sdk

    neatlogs._reset_for_tests()
    monkeypatch.delenv("NEATLOGS_ENABLED", raising=False)
    monkeypatch.setenv("NEATLOGS_API_KEY", "present-but-must-not-export")

    called = False

    def unexpected_init(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(sdk, "init", unexpected_init)
    assert neatlogs.initialize() is False
    assert neatlogs.enabled() is False
    assert called is False
    with neatlogs.workflow_span("test.disabled") as trace:
        assert trace.trace_id is None
    neatlogs._reset_for_tests()


def test_real_sdk_builds_nested_spans_and_isolates_concurrent_cases(sdk_capture):
    with neatlogs.workflow_span("test.workflow") as root:
        contexts = [neatlogs.copy_current_context() for _ in range(4)]

        def run_case(index: int) -> tuple[str | None, str | None]:
            with neatlogs.span("test.case", kind="AGENT", trial=index) as case:
                with neatlogs.span(
                    "test.tool",
                    kind="TOOL",
                    tool_name=neatlogs.safe_identifier(f"tool-{index}", "tool"),
                ) as tool:
                    return case.trace_id, tool.trace_id

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(context.run, run_case, i) for i, context in enumerate(contexts)]
            ids = [future.result() for future in futures]

    spans = sdk_capture.get_finished_spans()
    roots = [item for item in spans if item.name == "test.workflow"]
    cases = [item for item in spans if item.name == "test.case"]
    tools = [item for item in spans if item.name == "test.tool"]
    assert len(roots) == 1
    assert len(cases) == len(tools) == 4
    root_context = roots[0].context
    assert root.trace_id == f"{root_context.trace_id:032x}"
    assert all(case.parent.span_id == root_context.span_id for case in cases)
    case_span_ids = {case.context.span_id for case in cases}
    assert {tool.parent.span_id for tool in tools} == case_span_ids
    assert all(case_id == root.trace_id == tool_id for case_id, tool_id in ids)


def test_real_sdk_wraps_openai_once_and_creates_one_llm_span(sdk_capture):
    import httpx
    from openai import OpenAI

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "mock-completion",
                "object": "chat.completion",
                "created": 1,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "safe response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
            request=request,
        )

    client = OpenAI(
        api_key="test-only-not-a-real-key",
        base_url="https://example.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    first = neatlogs.wrap_client(client)
    second = neatlogs.wrap_client(first)
    assert first is second

    with neatlogs.workflow_span("test.openai"):
        response = second.chat.completions.create(
            model="mock-model", messages=[{"role": "user", "content": "hello"}]
        )
    assert response.choices[0].message.content == "safe response"
    llm_spans = [
        item
        for item in sdk_capture.get_finished_spans()
        if item.name == "openai.chat.completions.create"
    ]
    assert len(llm_spans) == 1


def test_eval_threads_share_one_workflow_and_keep_transcripts_local(
    sdk_capture, toy_package, evaluator_path, ledger, knobs, tmp_path
):
    answers = {
        "t1": {"category": "billing", "priority": "p1"},
        "t2": {"category": "bug", "priority": "p0"},
        "t3": {"category": "feature", "priority": "p3"},
    }

    def complete(messages, model, tools=None):
        del model, tools
        user = next(message["content"] for message in messages if message["role"] == "user")
        case_id = user.split("Case id: ", 1)[1].splitlines()[0]
        return {
            "text": json.dumps(answers[case_id]),
            "usage": {"tokens_in": 3, "tokens_out": 2},
        }

    summary = run_eval(
        "toy",
        package=toy_package,
        evaluator_path=evaluator_path,
        trials=1,
        knobs=replace(knobs, eval_concurrency=3),
        complete=complete,
        emit=ledger.emit,
        read_events=ledger.read,
        runs_dir=tmp_path / "runs",
    )
    assert all(Path(outcome.transcript_path).exists() for outcome in summary.cases)
    assert all(outcome.trace_url is None for outcome in summary.cases)

    spans = sdk_capture.get_finished_spans()
    roots = [item for item in spans if item.name == "task_orchestrator.eval"]
    cases = [item for item in spans if item.name == "task_orchestrator.case"]
    assert len(roots) == 1
    assert len(cases) == len(summary.cases) == 3
    assert all(case.context.trace_id == roots[0].context.trace_id for case in cases)
    assert all(case.parent.span_id == roots[0].context.span_id for case in cases)
    assert all(
        str(case.attributes["task_orchestrator.case_id"]).startswith("case_") for case in cases
    )


def test_fake_client_injection_is_never_wrapped_and_reset_still_works(monkeypatch):
    fake = FakeLLM([text("ok")])
    wrapped: list[object] = []
    monkeypatch.setattr(neatlogs, "wrap_client", lambda client: wrapped.append(client) or client)
    llm.set_client(fake)
    try:
        assert llm.get_client() is fake
        assert llm.get_client() is fake
        assert wrapped == []
    finally:
        llm.reset_client()


def test_real_llm_client_cache_requests_one_wrap_and_reset_rebuilds(monkeypatch):
    calls: list[object] = []
    monkeypatch.setenv("LLM_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setattr(neatlogs, "enabled", lambda: True)
    monkeypatch.setattr(neatlogs, "wrap_client", lambda client: calls.append(client) or client)
    llm.reset_client()
    try:
        first = llm.get_client()
        assert llm.get_client() is first
        assert calls == [first]
        llm.reset_client()
        second = llm.get_client()
        assert second is not first
        assert calls == [first, second]
    finally:
        llm.reset_client()


def test_mask_omits_content_redacts_pii_and_credentials_and_bounds_values(monkeypatch):
    monkeypatch.delenv("NEATLOGS_CAPTURE_CONTENT", raising=False)
    masked = neatlogs.telemetry_mask(
        {
            "attributes": {
                "input.value": "person@example.com " + "x" * 10_000,
                "authorization": "Bearer do-not-export",
                "neatlogs.llm.token_count.prompt": 17,
            },
            "events": [
                {
                    "attributes": {
                        "error.message": "secret body",
                        "status.description": "private customer prompt-like value",
                    }
                }
            ],
        }
    )
    assert masked["attributes"]["input.value"] == "[content omitted]"
    assert masked["attributes"]["authorization"] == "[redacted]"
    assert masked["attributes"]["neatlogs.llm.token_count.prompt"] == 17
    assert masked["events"][0]["attributes"]["error.message"] == "[content omitted]"
    assert masked["events"][0]["attributes"]["status.description"] == "[content omitted]"

    monkeypatch.setenv("NEATLOGS_CAPTURE_CONTENT", "true")
    captured = neatlogs.telemetry_mask(
        {"attributes": {"output.value": "person@example.com " + "x" * 10_000}}
    )
    value = captured["attributes"]["output.value"]
    assert "person@example.com" not in value
    assert "[redacted]" in value
    assert len(value) <= 2_048


def test_span_failures_do_not_repeat_work_or_lose_local_transcript(monkeypatch, tmp_path, caplog):
    class BrokenManager:
        def __enter__(self):
            raise RuntimeError("contains a secret that must not be logged")

        def __exit__(self, *args):
            raise AssertionError("unreachable")

    import neatlogs as sdk

    monkeypatch.setattr(neatlogs, "enabled", lambda: True)
    monkeypatch.setattr(sdk, "trace", lambda *args, **kwargs: BrokenManager())
    caplog.set_level(logging.WARNING, logger="backend.runtime.neatlogs")
    transcript = Transcript(
        run_id="run_local",
        agent_id="agent_local",
        agent_version=0,
        case_id="case_local",
        trial=0,
        orchestration="react",
        case_input={"private": "stays local"},
        expected_keys=[],
        system_prompt="local prompt",
    )
    calls = 0
    for _ in range(2):
        with neatlogs.trace_case():
            calls += 1
            transcript.record_note("business work completed")
    transcript.finish()
    path = transcript.write(tmp_path)
    assert calls == 2
    assert "business work completed" in Path(path).read_text(encoding="utf-8")
    warnings = [record.message for record in caplog.records if "span start" in record.message]
    assert len(warnings) == 1
    assert "contains a secret" not in warnings[0]


def test_shutdown_uses_one_bounded_flush_and_shutdown(monkeypatch):
    import neatlogs as sdk

    calls: list[tuple[str, int]] = []
    neatlogs._reset_for_tests()
    monkeypatch.setattr(neatlogs, "_active", True)
    monkeypatch.setenv("NEATLOGS_SHUTDOWN_TIMEOUT_MS", "999999")
    monkeypatch.setattr(
        sdk, "flush", lambda timeout_millis: calls.append(("flush", timeout_millis)) or True
    )
    monkeypatch.setattr(
        sdk,
        "shutdown",
        lambda timeout_millis: calls.append(("shutdown", timeout_millis)) or True,
    )
    assert neatlogs.shutdown()
    assert neatlogs.shutdown()
    assert [name for name, _timeout in calls] == ["flush", "shutdown"]
    assert sum(timeout for _name, timeout in calls) <= 5_000
    neatlogs._reset_for_tests()
