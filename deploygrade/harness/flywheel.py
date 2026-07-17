import json
import sys
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact

observation = json.loads(Path(sys.argv[1]).read_text())
validate_artifact(observation)
print(json.dumps({"status": "QUEUED_FOR_TRANSPARENT_REFIT", "vertical": observation["vertical"], "rubric_version": observation["rubric_version"]}, sort_keys=True))
