"""SessionStart: load prior customer memory before the first goal handoff."""
import json
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact


def load_customer_memory(path: str | Path) -> dict:
    memory = json.loads(Path(path).read_text())
    validate_artifact(memory)
    if "customer_id" not in memory:
        raise ValueError("customer memory must identify the customer")
    return memory
