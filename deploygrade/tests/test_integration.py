import hashlib
import json
import unittest
from pathlib import Path

from deploygrade.engine.blueprint import compile_blueprint
from deploygrade.engine.network import readout


class IntegrationTests(unittest.TestCase):
    def test_v2_shift_tightens_rollback_gate(self):
        score = json.loads(Path('deploygrade/sites/dashboard/readiness_score.json').read_text())
        policy = json.loads(Path('deploygrade/fixtures/policy_pack.json').read_text())
        compile_blueprint(score, policy, 'x')
        v2_score = {**score, 'score': {**score['score'], 'rubric_version': 'v2', 'value': 494}, 'sub_scores': [dict(item) for item in score['sub_scores']]}
        v2_score['sub_scores'][2]['raw'] = 10
        v2_score['confidence'] = {**score['confidence'], 'interval_low': 99}
        v2_score['audit'] = {**score['audit'], 'rubric_version': 'v2'}
        unsigned_audit = {key: value for key, value in v2_score['audit'].items() if key != 'signature'}
        v2_score['audit']['signature'] = hashlib.sha256(json.dumps(unsigned_audit, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        v2 = compile_blueprint(v2_score, policy, 'x')
        rollback = next(rule for rule in v2['rollback_rules'] if rule['because']['sub_score'] == 'rollback_recovery')
        self.assertEqual(rollback['effect'], 'DENY')
        self.assertLess(v2_score['sub_scores'][2]['raw'], score['sub_scores'][2]['raw'])

    def test_network_value(self):
        network = readout()
        self.assertEqual(network['prior_deployments'], 181)
        self.assertGreater(network['holdout_accuracy_after'], network['holdout_accuracy_before'])
