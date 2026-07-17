"""Score-aware alerting with remediation and replay handoff."""
def cost_spike(deployment_id,score,cost):
 severity='CRITICAL' if cost>1000 and score<600 else 'HIGH'
 return {'deployment_id':deployment_id,'severity':severity,'remediation':'cap spend and require human approval','sla':'15m','investigate_handoff':f'replay://investigate/{deployment_id}','evidence_uris':['metric://cost-spike']}
