export interface AgentCreationFingerprint {
  goal: string;
  domain: string;
  evaluator_id: string;
}

export interface AgentCreationCandidate extends AgentCreationFingerprint {
  agent_id: string;
}

/**
 * A timed-out create is only safe to reconcile against agents that did not
 * exist immediately before the POST. Return a candidate only when the match
 * is unambiguous; never guess between concurrent, identical submissions.
 */
export function findUniqueCreatedAgent<T extends AgentCreationCandidate>(
  agents: readonly T[],
  existingAgentIds: ReadonlySet<string>,
  submitted: AgentCreationFingerprint,
): T | null {
  const matches = agents.filter(
    (agent) =>
      !existingAgentIds.has(agent.agent_id) &&
      agent.goal === submitted.goal &&
      agent.domain === submitted.domain &&
      agent.evaluator_id === submitted.evaluator_id,
  );
  return matches.length === 1 ? matches[0] : null;
}

/** Identify only the indeterminate failure produced by the create proxy. */
export function isCreateAgentTimeout(
  error: unknown,
): error is { status: number; path: string } {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { status?: unknown; path?: unknown };
  return candidate.status === 504 && candidate.path === "/agents";
}
