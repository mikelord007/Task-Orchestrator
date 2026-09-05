"""One module per GitHub tool.

Each module here is a thin, self-contained tool surface (``TOOL`` + ``run``)
over the shared client in ``toolbox.github``. Splitting them keeps the registry
uniform -- every entry in ``TOOLBOX`` is a module with the same two names -- and
lets ``write_agent_tool`` emit a one-line re-export into an agent package.

Every tool in this package is read-only. Nothing here creates, edits, closes,
labels, assigns or comments on anything; the agent proposes triage, a human
applies it.
"""
