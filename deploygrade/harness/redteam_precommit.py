#!/usr/bin/env python3
"""Attempt to stage a fake score in an isolated index; policy must reject it."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as temporary:
    index = Path(temporary) / "index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    subprocess.run(["git", "read-tree", "HEAD"], cwd=ROOT, env=env, check=True)
    fake = Path(temporary) / "fake_score.py"
    fake.write_text("def score_bypass():\n    return 1000\n")
    staged_path = "deploygrade/engine/fake_score.py"
    subprocess.run(["git", "update-index", "--add", "--cacheinfo", "100644," + subprocess.check_output(["git", "hash-object", "-w", str(fake)], cwd=ROOT, text=True).strip() + "," + staged_path], cwd=ROOT, env=env, check=True)
    result = subprocess.run(["python3", "deploygrade/harness/precommit_guard.py"], cwd=ROOT, env=env, text=True, capture_output=True)
    print(result.stderr.strip())
    if result.returncode == 0:
        raise SystemExit("REDTEAM FAILURE: fake score bypassed pre-commit policy")
    if "scoring path staged without a matching determinism test" not in result.stderr:
        raise SystemExit("REDTEAM FAILURE: hook rejected for an unexpected reason")
    print("redteam: PASS — fake score was blocked")
