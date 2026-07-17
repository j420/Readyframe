import unittest
from pathlib import Path

from deploygrade.engine.discovery import CHECKS, discover

ROOT = Path("deploygrade/fixtures/discovery_repos")


class DiscoveryTests(unittest.TestCase):
    def test_mature_repo_collects_mapped_quality_tagged_facts(self):
        inventory = discover(ROOT / "mature", "staging")
        self.assertEqual(len(inventory["collected_facts"]), len(CHECKS))
        self.assertEqual(inventory["missing_evidence"], [])
        for fact in inventory["collected_facts"]:
            self.assertTrue(fact["sub_score"])
            self.assertEqual(set(fact["evidence_quality"]), {"source", "freshness", "confidence"})
            self.assertEqual(fact["status"], "present")
            self.assertLess(fact["evidence_quality"]["confidence"], 1)  # static evidence is still inferred.

    def test_bare_repo_records_every_missing_evidence_category(self):
        inventory = discover(ROOT / "bare")
        self.assertEqual(inventory["collected_facts"], [])
        self.assertEqual({gap["category"] for gap in inventory["missing_evidence"]}, {category for category, _ in CHECKS})
        self.assertTrue(all(gap["evidence_quality"]["freshness"] == "not_observed" for gap in inventory["missing_evidence"]))

    def test_deceptive_repo_is_present_but_low_quality_not_credited(self):
        inventory = discover(ROOT / "deceptive")
        self.assertEqual(len(inventory["collected_facts"]), len(CHECKS))
        for fact in inventory["collected_facts"]:
            self.assertEqual(fact["status"], "present_low_quality")
            self.assertLessEqual(fact["evidence_quality"]["confidence"], .15)
            self.assertIn("insufficient", fact["finding"])

    def test_missing_or_low_quality_discovery_evidence_reduces_score_confidence(self):
        from deploygrade.engine.score import score_readiness
        inventory = discover(ROOT / "deceptive")
        score = score_readiness({"$schema": "../schemas/readiness-input.schema.json", "rubric_version": "r1", "controls": {"safety": 1}, "discovery_inventory": inventory})
        self.assertLessEqual(score["score"]["confidence"], .15)
        self.assertTrue(any("low-quality" in driver["detail"] for driver in score["confidence"]["drivers"]))
