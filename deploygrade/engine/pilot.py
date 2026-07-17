"""Workspace-contained pilot controller with deny-before-execution and compensating revert."""
import json, statistics, subprocess
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact


def blast_radius(action: dict) -> dict:
    files=action.get("files",[]); services=action.get("services",[]); data=bool(action.get("data_touched"))
    score=len(files)+2*len(services)+3*data
    return {"files":len(files),"services":len(services),"data_touched":data,"reversibility":action.get("reversibility","HIGH"),"score":score}

class PilotController:
    def __init__(self, blueprint, workspace, metrics, timestamp="1970-01-01T00:00:00Z"):
        validate_artifact(blueprint); self.blueprint=blueprint; self.root=Path(workspace).resolve(); self.metrics=list(metrics); self.timestamp=timestamp; self.unsafe_scripts=set(); self.log=[]
    def pre_tool_use(self, action):
        radius=blast_radius(action); self.log.append({"action_id":action["id"],"blast_radius":radius})
        target=Path(action.get("path",self.root)).resolve()
        if self.root not in [target,*target.parents]: return False,"DENY: outside pilot workspace"
        if action["kind"]=="write_script" and action.get("dangerous",False): self.unsafe_scripts.add(target); return True,"contained write"
        if action["kind"] in {"merge","run_script"} and (action["kind"]=="merge" or target in self.unsafe_scripts): return False,"DENY: rollback policy requires safe pre-execution gate"
        return True,"ALLOW"
    def monitor(self, action, landed_commit=None):
        baseline=self.metrics[:-1] or self.metrics; value=self.metrics[-1]; sigma=max(statistics.pstdev(baseline),1); radius=blast_radius(action); limit=statistics.mean(baseline)+(1.25 if radius["score"]>=4 else 2)*sigma
        if value<=limit: return None
        status="NOTHING_TO_REVERT"
        if landed_commit:
            subprocess.run(["git","revert","--no-edit",landed_commit],cwd=self.root,check=True,capture_output=True);status="REVERTED"
        outcome={"$schema":"../schemas/outcome_record.schema.json","schema_version":"1.0","deployment_id":"anonymized-pilot","vertical":"healthcare","source_tag":"customer-anonymized","anonymized_id":"a"*64,"predicted":{"outcome":"safe","score":0},"observed":{"outcome":"metric_breach","evidence_uris":["metric://finding-spike"]},"prediction_evidence_quality":{"value":.2,"method":"rollback","missing_evidence_uris":[],"stale_evidence_uris":[]}}
        event={"$schema":"../schemas/rollback_event.schema.json","schema_version":"1.0","signal":"ROLLBACK FIRED","action_id":action["id"],"reason":f"metric {value} exceeded blast-aware threshold {limit}","blast_radius":radius,"revert_status":status,"remediation":"Add automated rollback verification, then re-qualify through the lowest-blast pilot.","post_incident_note":"A finding spike crossed the blast-radius-aware threshold; the landed change was compensating-reverted and rollback verification is now required before re-qualification.","outcome_record":outcome}
        (self.root / "outcome_record.json").write_text(json.dumps(outcome, sort_keys=True))
        validate_artifact(event); return event
