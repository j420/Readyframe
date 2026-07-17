import unittest
from deploygrade.engine.knowledge import load,pattern,anonymize
class KnowledgeTests(unittest.TestCase):
 def test_pattern_poison_and_anonymization(self):
  a,q=load('deploygrade/knowledge/outcome_records.jsonl'); p=pattern(a)
  self.assertGreater(p['low_rollback_records'],50);self.assertEqual(len(q),31);self.assertTrue(all(reason in {'low_evidence_quality','untrusted_source'} for _,reason in q))
  self.assertNotIn('customer-0',a[0][0]['anonymized_id']);self.assertNotEqual(anonymize('customer-0'),'customer-0')
