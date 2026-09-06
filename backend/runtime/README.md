# backend/runtime

The agent runtime and eval harness: package loading, the tool-use loop,
orchestration modes, the drift watchdog, memory injection, and `run_eval`.

## Estimated vs. measured numbers

Every number in a transcript or `case_result` is either taken directly from
the API's `usage` field (`request`/`response` step `tokens_in`/`tokens_out`,
and the top-level transcript totals) or explicitly flagged as an estimate.

The one estimate: a `tool_return` step's `tokens_in` is `len(result) // 4`
(~4 characters per token), not a measurement - the LLM API gives no per-tool-
call token attribution, only a total for the next request's growing prompt.
The step carries `tokens_estimated: true` so a consumer (W1's
`tool_call_stats`, W9's charts) never reads it as measured; label any chart
built from it "tool tokens (est.)".

## Neatlogs tracing

Tracing is fail-open for the application and fail-closed for telemetry. It is
disabled unless both `NEATLOGS_ENABLED=true` and `NEATLOGS_API_KEY` are set.
The SDK initializes once in the FastAPI lifespan, wraps only the real cached
OpenAI client, batches in the background, then performs one bounded flush and
shutdown during graceful server termination. Local transcripts and ledger
events remain authoritative and are written whether tracing succeeds or not.

By default, exported spans contain hashed run/job/agent/case/evaluator IDs,
versions, trials, split/lever labels, timing, model, and token metadata. Prompt,
response, tool, and exception content is omitted. Setting
`NEATLOGS_CAPTURE_CONTENT=true` additionally exports content after local
credential/PII redaction and size bounds. Typed-media uploads and log/stdout
capture remain disabled.

For a later production rollout, configure the API key in the deployment secret
store, set `NEATLOGS_ENABLED=true`, restart, and exercise one approved eval.
Verify that exact hosted trace and its finalized workflow → case → LLM/tool
tree; a local Doctor pass alone does not prove hosted ingestion. Roll back by
setting `NEATLOGS_ENABLED=false` and restarting. `trace_url` remains optional
and null because the SDK does not document a dashboard-link constructor.
