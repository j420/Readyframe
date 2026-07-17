"""Print the audited, mechanically enforceable bare-repo rollout blueprint."""
import json
from deploygrade.engine.blueprint import compile_blueprint

readiness = json.load(open("deploygrade/sites/dashboard/readiness_score.json"))
policy = json.load(open("deploygrade/fixtures/policy_pack.json"))
blueprint = compile_blueprint(readiness, policy, "bare-repo-pilot")
for gate in blueprint["rollback_rules"] + blueprint["approval_gates"]:
    print(json.dumps({"gate": gate.get("id", gate.get("when")), "effect": gate.get("effect", "APPROVAL"), "because": gate["because"]}, sort_keys=True))
print(json.dumps({"autonomy_level": blueprint["autonomy_level"], "budget": blueprint["budget"], "pilot_repos": blueprint["pilot_repos"]}, sort_keys=True))
