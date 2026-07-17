"""Adversarial check: a legacy model fallback must be rejected before use."""
import tomllib
from pathlib import Path
from deploygrade.engine.agent_policy import validate_agent_policy

agents = {path.stem: tomllib.loads(path.read_text())["agent"] for path in Path("deploygrade/agents").glob("*.toml")}
agents["discovery"] = {**agents["discovery"], "model": "terra"}
try:
    validate_agent_policy(agents)
except ValueError as error:
    print(f"model routing redteam: PASS — {error}")
else:
    raise SystemExit("model routing redteam: FAILURE — legacy fallback was accepted")
