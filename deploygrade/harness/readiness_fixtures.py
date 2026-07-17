"""Print readiness signal, confidence interval, counterfactual, and audit for fixture repos."""
import json
from deploygrade.engine.discovery import discover
from deploygrade.engine.readiness import assess

for name in ("mature", "bare", "deceptive"):
    score = assess(discover(f"deploygrade/fixtures/discovery_repos/{name}"))
    print(json.dumps({"repo": name, "score": score["score"], "band": score["band"], "confidence": score["confidence"], "counterfactual": score["counterfactual"], "audit": score["audit"]}, sort_keys=True))
