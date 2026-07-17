import json
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread
import unittest

from api.score import calculate, handler


class VercelScoreApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def setUp(self):
        with open("deploygrade/fixtures/readiness-input.json") as fixture:
            self.payload = json.load(fixture)

    def test_score_response_is_schema_valid_and_deterministic(self):
        first = calculate(self.payload)
        self.assertEqual(first, calculate(self.payload))
        self.assertEqual(first["$schema"], "../schemas/readiness_score.schema.json")
        self.assertEqual(set(first["score"]), {"value", "confidence", "evidence_uris", "rubric_version"})
        self.assertTrue(first["counterfactual"])

    def test_invalid_request_is_rejected_before_scoring(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            calculate([])

    def test_unpublished_rubric_and_non_finite_number_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "not published"):
            calculate({**self.payload, "rubric_version": "unpublished"})
        payload = json.loads(json.dumps(self.payload))
        payload["controls"]["access_control"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite number"):
            calculate(payload)

    def test_http_handler_rejects_wrong_content_type_and_returns_json_artifact(self):
        connection = HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request("POST", "/api/score", body=json.dumps(self.payload), headers={"Content-Type": "text/plain"})
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        self.assertIn("Content-Type", json.loads(response.read())["error"])
        connection.request("POST", "/api/score", body=json.dumps(self.payload), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        artifact = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("X-DeployGrade-Input-Trust"), "unverified-declared-evidence")
        self.assertEqual(artifact["score"]["rubric_version"], "2026.07.0")
