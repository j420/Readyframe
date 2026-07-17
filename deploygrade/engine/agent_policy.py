"""Enforce the explicit all-sol-5.6 routing policy without relaxing sandbox roles."""
REQUIRED_AGENTS = {"discovery", "readiness", "blueprint", "pilot", "scale", "replay", "cross_customer", "strategic", "portfolio", "risk"}
MODEL_ID = "sol-5.6"


def validate_agent_policy(agents: dict[str, dict]) -> None:
    if set(agents) != REQUIRED_AGENTS:
        raise ValueError("agent policy mismatch: expected exactly the ten DeployGrade roles")
    mismatched = [name for name, agent in agents.items() if agent.get("model") != MODEL_ID]
    if mismatched:
        raise ValueError(f"agent policy mismatch: {MODEL_ID} required for {sorted(mismatched)}")
    if agents["pilot"].get("sandbox") != "workspace-write":
        raise ValueError("agent policy mismatch: pilot must retain workspace-write")
    if any(agent.get("sandbox") != "read-only" for name, agent in agents.items() if name != "pilot"):
        raise ValueError("agent policy mismatch: non-pilot agents must remain read-only")
