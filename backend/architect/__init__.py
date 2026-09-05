"""The architect: turns (goal, domain, tools, evaluator_id, use_playbook) into agents/<id>/v0/.

See ``generate.generate`` for the entry point. This package is written before
Phase 0 (``contracts/``, ``backend/db.py``, ``backend/llm.py``,
``backend/ledger/emit.py``) lands on ``main``; every dependency on those is a
lazy import so the module tree here imports and its steps run today against an
injected fake LLM. See ``generate._finalize`` for exactly what is deferred.
"""
