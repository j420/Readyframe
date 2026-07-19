import unittest
from pathlib import Path
from unittest.mock import patch

from deploygrade.engine.rubrics import content_hash, load
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

    def test_rubric_content_hash_is_stable_and_carried_by_score_audit(self):
        payload = {
            "$schema": "../schemas/readiness-input.schema.json",
            "rubric_version": "2026.07.0",
            "controls": {"access_control": 1, "rollback_plan": 1, "observability": 1},
        }
        self.assertEqual(content_hash("2026.07.0"), content_hash("2026.07.0"))
        self.assertEqual(score_readiness(payload)["audit"]["rubric_hash"], content_hash("2026.07.0"))

    def test_published_rubric_mutation_is_rejected_by_immutable_manifest(self):
        import deploygrade.engine.rubrics as rubrics

        original = rubrics.ROOT / "2026.07.0.json"
        mutated = original.read_text().replace('"vertical": "baseline"', '"vertical": "tampered"')
        original_read_text = Path.read_text
        with patch.object(rubrics.Path, "read_text", autospec=True) as read_text:
            def read(path, *args, **kwargs):
                return mutated if path == original else original_read_text(path, *args, **kwargs)

            read_text.side_effect = read
            with self.assertRaisesRegex(ValueError, "immutable manifest"):
                load("2026.07.0")
