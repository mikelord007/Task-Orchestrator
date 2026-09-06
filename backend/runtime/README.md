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
