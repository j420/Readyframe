"""Honest local fallbacks: call the same deterministic computation, never canned output."""
from deploygrade.engine.flywheel import hero
def network_off_demo(): return hero()
def manual_rollback(controller,action,commit): return controller.monitor(action,commit)
