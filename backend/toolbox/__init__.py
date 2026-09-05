"""Reusable tool library for generated agents.

Every tool module in this package exposes exactly two public names:

- ``TOOL``: ``{"name": str, "description": str, "input_schema": dict}`` — a
  JSON-Schema tool definition suitable for passing straight to an LLM's tool
  parameter.
- ``run(input: dict) -> str``: executes the tool. It always returns a string;
  structured results are JSON-encoded. It never raises for expected failure
  modes (bad arguments, missing data, network trouble) — those come back as a
  human-readable string starting with ``ERROR:`` so the agent can read the
  problem and adapt.

Use ``toolbox.registry`` to look tools up by name and to materialise them into
an agent package.
"""
