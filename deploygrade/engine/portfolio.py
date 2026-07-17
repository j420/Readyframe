"""Deterministic decision-useful portfolio ordering."""
def aggregate(rows):
 return sorted(rows,key=lambda x:(-x['risk'],-x['velocity'],x['deployment_id']))
