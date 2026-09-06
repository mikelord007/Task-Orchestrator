"""Cross-agent memory: distill lessons from accepted fixes, serve them, and
ablate their effect on a fresh agent (contracts/playbook.md, PLAN.md 4.4)."""

from .scan import scan_and_record

__all__ = ["scan_and_record"]
