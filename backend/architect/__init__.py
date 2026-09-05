"""The architect: turns (goal, domain, tools, evaluator_id, use_playbook) into agents/<id>/v0/.

See ``generate.generate`` for the entry point and ``api`` for the HTTP surface
(``POST /agents``, ``GET /agents``, ``GET /agents/{id}``,
``GET /agents/{id}/versions/{n}``, ``GET /evaluators``).
"""
