import tempfile, subprocess, unittest
from pathlib import Path
from deploygrade.engine.pilot import PilotController
import json
B=json.load(open('deploygrade/fixtures/rollout_blueprint.json'))
class PilotTests(unittest.TestCase):
 def repo(self):
  d=tempfile.TemporaryDirectory(); p=Path(d.name); subprocess.run(['git','init'],cwd=p,check=True,capture_output=True);subprocess.run(['git','config','user.email','t@e'],cwd=p);subprocess.run(['git','config','user.name','t'],cwd=p);(p/'x').write_text('a');subprocess.run(['git','add','.'],cwd=p);subprocess.run(['git','commit','-m','base'],cwd=p,capture_output=True);(p/'x').write_text('b');subprocess.run(['git','commit','-am','landed'],cwd=p,capture_output=True);return d,p,subprocess.check_output(['git','rev-parse','HEAD'],cwd=p,text=True).strip()
 def test_spike_denies_merge_and_reverts_landed(self):
  d,p,c=self.repo(); self.addCleanup(d.cleanup); ctl=PilotController(B,p,[10,10,10,13]); a={'id':'merge','kind':'merge','files':['x'],'services':['api'],'reversibility':'LOW'}; self.assertFalse(ctl.pre_tool_use(a)[0]); e=ctl.monitor(a,c);self.assertEqual(e['signal'],'ROLLBACK FIRED');self.assertEqual(e['revert_status'],'REVERTED');self.assertTrue((p/'outcome_record.json').is_file());self.assertIn('finding spike', e['post_incident_note'])
 def test_no_spike_and_bypass_contained(self):
  d,p,c=self.repo(); self.addCleanup(d.cleanup);ctl=PilotController(B,p,[10,10,10,11]);a={'id':'safe','kind':'deploy','files':['x']};self.assertIsNone(ctl.monitor(a,c)); script=p/'evil.sh';self.assertTrue(ctl.pre_tool_use({'id':'write','kind':'write_script','path':str(script),'dangerous':True})[0]);self.assertFalse(ctl.pre_tool_use({'id':'run','kind':'run_script','path':str(script)})[0]);self.assertTrue(all(ctl.monitor(a,c) is None for _ in range(5)))
