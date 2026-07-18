import json
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread
import unittest

from api.demo import handler
from deploygrade.engine.contracts import validate_artifact


class VercelDemoApiTests(unittest.TestCase):
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

    def request(self, method, path):
        connection = HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_ambiguous_and_unknown_query_parameters_fail_closed(self):
        for path in ("/api/demo?profile=mature&profile=deceptive", "/api/demo?unexpected=1"):
            status, artifact = self.request("GET", path)
            self.assertEqual(status, 400)
            validate_artifact(artifact)

    def test_unsupported_methods_return_schema_valid_errors(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            status, artifact = self.request(method, "/api/demo")
            self.assertEqual(status, 405)
            validate_artifact(artifact)
