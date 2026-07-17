import unittest

from deploygrade.engine.contracts import validate_schema_shape


class ContractDeterminismTests(unittest.TestCase):
    def test_non_finite_values_are_rejected_deterministically(self):
        artifact = {"$schema": "../schemas/readiness-input.schema.json", "rubric_version": "2026.07.0", "controls": {"access_control": float("nan")}}
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "finite number"):
                validate_schema_shape(artifact)
