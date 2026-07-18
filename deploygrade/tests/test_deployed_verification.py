import json
import unittest

from deploygrade.engine.demo_flow import run
from deploygrade.harness.verify_deployed import deployed_demo_url, verify


class _Headers:
    def get_content_type(self):
        return "application/json"


class _Response:
    status = 200
    headers = _Headers()

    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class DeployedVerificationTests(unittest.TestCase):
    def test_deployed_url_requires_a_clean_https_origin(self):
        self.assertEqual(deployed_demo_url("https://deploygrade.example"), "https://deploygrade.example/api/demo?profile=mature")
        for origin in ("http://deploygrade.example", "https://deploygrade.example?x=1", "not-a-url"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                deployed_demo_url(origin)

    def test_live_response_is_validated_against_checked_in_contracts(self):
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            return _Response(run("mature"))

        self.assertEqual(verify("https://deploygrade.example", opener=opener)["$schema"], "../schemas/demo_run.schema.json")
        self.assertEqual(calls, [("https://deploygrade.example/api/demo?profile=mature", 15)])
