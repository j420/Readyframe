import json
import unittest

from deploygrade.engine.demo_flow import run
from deploygrade.engine.flywheel import hero, refit


class FlywheelDeterminismTests(unittest.TestCase):
    def test_published_refit_and_actual_rescore_are_identical(self):
        first = run("deceptive")["flywheel"]
        self.assertEqual(first, run("deceptive")["flywheel"])
        self.assertEqual(first["refit"]["rubric_version"], "2026.07.2")
        self.assertNotEqual(first["before"]["score"]["value"], first["after"]["score"]["value"])

    def test_refit_is_refused_for_poisoned_corpus(self):
        self.assertEqual(refit("deploygrade/knowledge/outcome_records.jsonl", "finance")["status"], "REFUSED")

    def test_refit_split_and_holdout_metrics_are_reproducible(self):
        first = refit("deploygrade/knowledge/outcome_records_clean.jsonl", "healthcare")
        second = refit("deploygrade/knowledge/outcome_records_clean.jsonl", "healthcare")
        self.assertEqual(first["corpus_hash"], second["corpus_hash"])
        self.assertEqual(first["holdout_records"], 7)
        self.assertEqual(first["baseline_accuracy"], 0.7143)
        self.assertEqual(first["holdout_accuracy"], 1.0)

    def test_published_refit_retains_stable_approval_and_parent_provenance(self):
        result = refit("deploygrade/knowledge/outcome_records_clean.jsonl", "healthcare")
        self.assertEqual(result["parent_rubric_version"], "2026.07.0")
        self.assertEqual(result["approval_id"], "approval://rubric/healthcare/2026.07.2")

    def test_demo_run_artifact_has_a_stable_contract(self):
        self.assertEqual(run("mature")["$schema"], "../schemas/demo_run.schema.json")
