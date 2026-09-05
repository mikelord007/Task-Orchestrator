from __future__ import annotations

import pytest

from backend import llm
from backend.testing.fake_llm import FakeLLM, FakeLLMExhausted, text, tool_call

TOOLS = [
    {
        "name": "shout",
        "description": "Uppercases text.",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
    }
]


@pytest.fixture
def fake():
    client = FakeLLM()
    llm.set_client(client)
    yield client
    llm.reset_client()


def test_replays_scripted_tool_calls_in_order(fake: FakeLLM):
    fake.push(
        tool_call("shout", {"text": "hello"}),
        text('{"answer": "HELLO!"}'),
    )

    first = llm.complete([{"role": "user", "content": "shout hello"}], "gpt-4o", tools=TOOLS)
    assert first["text"] == ""
    assert len(first["tool_calls"]) == 1
    assert first["tool_calls"][0]["name"] == "shout"
    assert first["tool_calls"][0]["arguments"] == {"text": "hello"}
    assert first["tool_calls"][0]["id"]

    second = llm.complete([{"role": "user", "content": "now answer"}], "gpt-4o")
    assert second["text"] == '{"answer": "HELLO!"}'
    assert second["tool_calls"] == []
    assert second["finish_reason"] == "stop"


def test_records_every_request(fake: FakeLLM):
    fake.push(text("ok"))
    llm.complete(
        [{"role": "system", "content": "you are toy"}, {"role": "user", "content": "hi"}],
        "gpt-4o-mini",
        tools=TOOLS,
    )

    assert fake.call_count == 1
    assert fake.last_request["model"] == "gpt-4o-mini"
    assert fake.messages_at(0)[0]["role"] == "system"
    assert fake.system_prompts() == ["you are toy"]
    assert fake.tool_names_offered() == ["shout"]
    # Contract TOOL dicts are converted to the OpenAI function shape.
    assert fake.last_request["tools"][0]["function"]["parameters"]["type"] == "object"


def test_usage_is_realistic_and_priced(fake: FakeLLM):
    fake.push(text("a fairly long answer " * 10))
    out = llm.complete([{"role": "user", "content": "x" * 400}], "gpt-4o")

    assert out["usage"]["tokens_in"] > 0
    assert out["usage"]["tokens_out"] > 0
    assert out["cost_usd"] > 0
    assert out["cost_usd"] == llm.cost_for(
        "gpt-4o", out["usage"]["tokens_in"], out["usage"]["tokens_out"]
    )
    assert out["latency_ms"] >= 0


def test_explicit_usage_overrides_the_estimate(fake: FakeLLM):
    fake.push(text("hi", tokens_in=1000, tokens_out=250))
    out = llm.complete([{"role": "user", "content": "hi"}], "gpt-4o")
    assert out["usage"] == {"tokens_in": 1000, "tokens_out": 250}


def test_exhausted_script_raises(fake: FakeLLM):
    fake.push(text("only one"))
    llm.complete([{"role": "user", "content": "hi"}], "gpt-4o")
    with pytest.raises(llm.LLMError) as exc:
        llm.complete([{"role": "user", "content": "hi"}], "gpt-4o")
    assert isinstance(exc.value.__cause__, FakeLLMExhausted)


def test_repeat_last_loops_forever_for_drift_tests():
    client = FakeLLM([tool_call("shout", {"text": "again"})], repeat_last=True)
    llm.set_client(client)
    try:
        for _ in range(5):
            out = llm.complete([{"role": "user", "content": "go"}], "gpt-4o", tools=TOOLS)
            assert out["tool_calls"][0]["name"] == "shout"
        assert client.call_count == 5
    finally:
        llm.reset_client()


def test_unknown_model_is_not_given_an_invented_price():
    assert llm.cost_for("some-local-model", 1_000_000, 1_000_000) == 0.0


def test_cost_table_prices_the_known_models():
    assert llm.cost_for("gpt-4o", 1_000_000, 0) == 2.5
    assert llm.cost_for("gpt-4o-mini", 0, 1_000_000) == 0.6


def test_model_for_tier():
    assert llm.model_for_tier("strong") == llm.MODEL_STRONG
    assert llm.model_for_tier("cheap") == llm.MODEL_CHEAP
    with pytest.raises(llm.LLMError):
        llm.model_for_tier("medium")
