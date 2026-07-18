import unittest
from unittest.mock import patch

from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.flywheel import hero, refit


class FlywheelTests(unittest.TestCase):
    def test_clean_healthcare_publishes_and_other_vertical_is_refused(self):
        healthcare = refit("deploygrade/knowledge/outcome_records_clean.jsonl", "healthcare")
        finance = refit("deploygrade/knowledge/outcome_records_clean.jsonl", "finance")
        self.assertEqual(healthcare["status"], "PUBLISHED")
        self.assertGreater(healthcare["holdout_accuracy"], healthcare["baseline_accuracy"])
        self.assertEqual(finance["status"], "REFUSED")

    def test_poison_refused(self):
        self.assertEqual(refit("deploygrade/knowledge/outcome_records.jsonl", "finance")["status"], "REFUSED")

    def test_hero(self):
        result = hero()
        self.assertEqual(result["refit"]["status"], "PUBLISHED")
        self.assertEqual(result["refit"]["rubric_version"], "2026.07.2")
        self.assertTrue(result["refit"]["rubric_hash"])

    def test_refit_artifact_is_schema_valid_and_has_stable_split_provenance(self):
        first = refit("deploygrade/knowledge/outcome_records_clean.jsonl", "healthcare")
        validate_artifact(first)
        self.assertEqual(first, refit("deploygrade/knowledge/outcome_records_clean.jsonl", "healthcare"))
        self.assertEqual(first["split_version"], "sha256-anonymized-id-v1")
        self.assertEqual(first["holdout_records"], 7)
        self.assertEqual(first["parent_rubric_version"], "2026.07.0")
        self.assertTrue(first["approval_id"])

    def test_refit_refuses_a_corpus_not_bound_to_the_published_release(self):
        from deploygrade.engine import flywheel

        accepted, quarantined = flywheel.load("deploygrade/knowledge/outcome_records_clean.jsonl")
        altered = [({**row, "deployment_id": "different-approved-corpus"} if row["vertical"] == "healthcare" else row, reason)
                   for row, reason in accepted]
        with patch.object(flywheel, "load", return_value=(altered, quarantined)):
            result = flywheel.refit("ignored.jsonl", "healthcare")
        self.assertEqual(result["status"], "REFUSED")
        self.assertEqual(result["reason"], "corpus is not the approved immutable publication corpus")
