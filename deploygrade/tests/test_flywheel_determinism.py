import json
import unittest

from deploygrade.engine.demo_flow import run
from deploygrade.engine.flywheel import hero, refit


class FlywheelDeterminismTests(unittest.TestCase):
    def test_published_refit_and_actual_rescore_are_identical(self):
        first = run("deceptive")["flywheel"]
        self.assertEqual(first, run("deceptive")["flywheel"])
        self.assertEqual(first["refit"]["rubric_version"], "2026.07.1")
        self.assertNotEqual(first["before"]["score"]["value"], first["after"]["score"]["value"])

    def test_refit_is_refused_for_poisoned_corpus(self):
        self.assertEqual(refit("deploygrade/knowledge/outcome_records.jsonl", "finance")["status"], "REFUSED")

    def test_demo_run_artifact_has_a_stable_contract(self):
        self.assertEqual(run("mature")["$schema"], "../schemas/demo_run.schema.json")
