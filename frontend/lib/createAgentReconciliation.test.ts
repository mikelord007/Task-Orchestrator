import assert from "node:assert/strict";
import test from "node:test";

import {
  findUniqueCreatedAgent,
  isCreateAgentTimeout,
} from "./createAgentReconciliation";

const submitted = {
  goal: "Triage repository issues",
  domain: "github_triage",
  evaluator_id: "github_triage",
};

test("finds one matching agent created after the request began", () => {
  const created = { agent_id: "new-agent", ...submitted };
  assert.equal(
    findUniqueCreatedAgent(
      [{ agent_id: "old-agent", ...submitted }, created],
      new Set(["old-agent"]),
      submitted,
    ),
    created,
  );
});

test("does not mistake an existing matching agent for the timed-out create", () => {
  assert.equal(
    findUniqueCreatedAgent(
      [{ agent_id: "old-agent", ...submitted }],
      new Set(["old-agent"]),
      submitted,
    ),
    null,
  );
});

test("does not guess when multiple new agents match", () => {
  assert.equal(
    findUniqueCreatedAgent(
      [
        { agent_id: "new-agent-1", ...submitted },
        { agent_id: "new-agent-2", ...submitted },
      ],
      new Set(),
      submitted,
    ),
    null,
  );
});

test("requires an exact request fingerprint", () => {
  assert.equal(
    findUniqueCreatedAgent(
      [{ agent_id: "new-agent", ...submitted, evaluator_id: "other" }],
      new Set(),
      submitted,
    ),
    null,
  );
});

test("recognizes only a 504 from POST /agents", () => {
  assert.equal(isCreateAgentTimeout({ status: 504, path: "/agents" }), true);
  assert.equal(isCreateAgentTimeout({ status: 502, path: "/agents" }), false);
  assert.equal(isCreateAgentTimeout({ status: 504, path: "/agents/id/run" }), false);
  assert.equal(isCreateAgentTimeout(new Error("backend request timed out")), false);
});
