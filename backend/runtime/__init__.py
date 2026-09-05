"""Agent runtime and eval harness.

Everything in here observes the agent at the *harness* level (PLAN.md rule 2.8):
the loop records what the agent actually did — every request, response, tool call,
tool return, token count and timestamp. Nothing asks the agent what it did or
whether it succeeded.
"""
