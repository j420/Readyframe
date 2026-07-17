import json
import sys
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact

payload = json.loads(Path(sys.argv[1]).read_text())
validate_artifact(payload)
# Fail closed: an incomplete control set denies progression before any execution.
required = {"access_control", "rollback_plan", "observability"}
missing = required - set(payload["controls"])
print(json.dumps({"decision": "DENY" if missing else "PAUSE_FOR_HUMAN", "reason": "missing controls" if missing else "human approval required before rollout"}, sort_keys=True))
