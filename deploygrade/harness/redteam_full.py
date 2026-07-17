"""Full deterministic red-team manifest: every case must report defended or documented."""
import subprocess,sys
cases=[('deceptive evidence','deploygrade.tests.test_discovery.DiscoveryTests.test_deceptive_repo_is_present_but_low_quality_not_credited'),('hook bypass + false-positive storm','deploygrade.tests.test_pilot'),('poison corpus + re-identification','deploygrade.tests.test_knowledge'),('cross-vertical leakage','deploygrade.tests.test_flywheel'),('fake hero beat','deploygrade.tests.test_fallbacks')]
failed=[]
for name,target in cases:
 r=subprocess.run([sys.executable,'-m','unittest',target],capture_output=True,text=True)
 print(f'{name}: {"DEFENDED" if r.returncode==0 else "DOCUMENTED FAILURE"}')
 if r.returncode: failed.append(name)
if failed: raise SystemExit('redteam silent failures: '+', '.join(failed))
