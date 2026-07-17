import itertools
import unittest
from deploygrade.engine.discovery import discover
from deploygrade.engine.score import DIMENSIONS, band_for, score_inventory

ROOT = "deploygrade/fixtures/discovery_repos"


class ReadinessTests(unittest.TestCase):
    def test_six_dimensions_cite_named_real_control_clauses(self):
        result = score_inventory(discover(f"{ROOT}/mature"))
        self.assertEqual(len(result["sub_scores"]), 6)
        clauses = {clause for item in result["sub_scores"] for clause in item["control_clauses"]}
        self.assertTrue({"PCI DSS 6.4.5.4", "SOC 2 CC8.1", "HIPAA 164.312", "NIST SP 800-53 CM-3", "NIST SP 800-53 CM-5"}.issubset(clauses))

    def test_same_input_is_identical_one_hundred_times(self):
        inventory = discover(f"{ROOT}/mature")
        outputs = [score_inventory(inventory) for _ in range(100)]
        self.assertTrue(all(output == outputs[0] for output in outputs))

    def test_degraded_evidence_widens_confidence_interval(self):
        mature = score_inventory(discover(f"{ROOT}/mature"))
        deceptive = score_inventory(discover(f"{ROOT}/deceptive"))
        mature_width = mature["confidence"]["interval_high"] - mature["confidence"]["interval_low"]
        deceptive_width = deceptive["confidence"]["interval_high"] - deceptive["confidence"]["interval_low"]
        self.assertGreater(deceptive_width, mature_width)
        self.assertTrue(deceptive["confidence"]["drivers"])

    def test_counterfactual_is_minimum_cost_by_brute_force(self):
        result = score_inventory(discover(f"{ROOT}/bare"))
        current, target = result["score"]["value"], 400
        actions = [(item, spec[4]) for item, spec in zip(result["sub_scores"], DIMENSIONS)]
        costs = []
        for size in range(1, len(actions) + 1):
            for group in itertools.combinations(actions, size):
                projected = round(current + sum((100 - item["raw"]) * item["weight"] * 10 for item, _ in group))
                if projected >= target:
                    costs.append(sum(cost for _, cost in group))
        self.assertEqual(sum(item["cost"] for item in result["counterfactual"]), min(costs))
        projected = current + sum(item["projected_score_delta"] for item in result["counterfactual"])
        self.assertEqual(band_for(round(projected)), "CONDITIONAL")

    def test_top_band_allows_no_counterfactual(self):
        from deploygrade.engine.score import _assemble
        sub_scores = [{"name": spec[0], "raw": 100, "weight": spec[1], "controls": list(spec[2]) or [spec[0]], "control_clauses": list(spec[3]), "evidence_uris": [f"evidence://{spec[0]}"], "evidence_quality": {"source": "test", "freshness": "current", "confidence": 1}} for spec in DIMENSIONS]
        result = _assemble(sub_scores, "r1", {"all_controls": "verified"}, [], 1)
        self.assertEqual(result["band"], "SCALE")
        self.assertEqual(result["counterfactual"], [])
