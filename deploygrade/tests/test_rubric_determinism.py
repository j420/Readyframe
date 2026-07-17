import unittest

from deploygrade.engine.rubrics import load
from deploygrade.engine.score import score_readiness


class RubricDeterminismTests(unittest.TestCase):
    def test_published_rubric_drives_identical_scores(self):
        rubric = load("2026.07.0")
        self.assertEqual(round(sum(item["weight"] for item in rubric["dimensions"]), 6), 1)
        payload = {"$schema": "../schemas/readiness-input.schema.json", "rubric_version": "2026.07.0", "controls": {"access_control": 1, "rollback_plan": 1, "observability": 1}}
        self.assertEqual(score_readiness(payload), score_readiness(payload))

    def test_unpublished_rubric_is_refused(self):
        with self.assertRaisesRegex(ValueError, "unpublished rubric"):
            load("rubric-v404")

    def test_published_band_thresholds_are_ordered(self):
        thresholds = [band["threshold"] for band in load("2026.07.0")["bands"]]
        self.assertEqual(thresholds, sorted(thresholds))

    def test_score_audit_carries_stable_rubric_content_hash(self):
        payload = {"$schema": "../schemas/readiness-input.schema.json", "rubric_version": "2026.07.0", "controls": {"access_control": 1}}
        self.assertEqual(score_readiness(payload)["audit"]["rubric_hash"], score_readiness(payload)["audit"]["rubric_hash"])
