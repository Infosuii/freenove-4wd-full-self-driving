import base64
from dataclasses import replace
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import Mock
from ai_driver.ollama import Ollama, OllamaError, JsonHTTP
from ai_driver.config import Config
from tests.helpers import jpeg, response


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.http = Mock()
        self.ollama = Ollama(self.config, self.http)
        self.success = [{"models": [{"name": self.config.model}]}, {"capabilities": ["completion", "vision"]},
                        {"done": True, "message": {"content": "Hi!"}},
                        {"done": True, "message": {"content": "Red"}}]

    def test_model_availability_hi_and_image_requests(self):
        self.http.side_effect = self.success
        self.assertTrue(self.ollama.test())
        calls = self.http.call_args_list
        self.assertEqual([c.args[1].split("11434")[1] for c in calls], ["/api/tags", "/api/show", "/api/chat", "/api/chat"])
        self.assertEqual(calls[2].args[2]["messages"][0]["content"], "hi")
        self.assertTrue(base64.b64decode(calls[3].args[2]["messages"][0]["images"][0]).startswith(b"\xff\xd8"))
        self.assertTrue(self.ollama.verified)
        self.assertEqual(self.ollama.status["result"], "SUCCESS")

    def test_missing_model_nonvision_and_unreachable(self):
        cases = [[{"models": []}], [self.success[0], {"capabilities": ["completion"]}],
                 [OSError("Connection refused")], [self.success[0], {"capabilities": "vision"}],
                 [self.success[0], self.success[1], {"error": "load failed"}],
                 [*self.success[:3], {"error": "model does not support images"}]]
        for results in cases:
            with self.subTest(results=results):
                self.http.side_effect = results
                self.assertFalse(self.ollama.test())
                self.assertFalse(self.ollama.verified)
                self.assertIn("FAILED", self.ollama.status["result"])

    def test_older_show_api_without_capabilities_uses_image_probe(self):
        self.http.side_effect = [self.success[0], {}, *self.success[2:]]
        self.assertTrue(self.ollama.test())
        self.assertEqual(self.ollama.status["vision"], "Image request accepted")

    def test_malformed_chat_responses(self):
        for result in ({}, {"done": False, "message": {"content": "Hi"}},
                       {"done": True, "message": {}}, {"done": True, "message": {"content": ""}},
                       {"done": True, "message": {"content": 12}}, {"message": None}, None, []):
            with self.subTest(result=result), self.assertRaises(OllamaError):
                self.ollama.content(result)

    def test_decision_schema_image_objective_and_bounded_context(self):
        self.ollama.verified = True
        self.http.return_value = {"done": True, "message": {"content": response()}}
        observation = {"objective": "Find red object", "ultrasonic_cm": 100, "frame_sequence": 3,
                       "mode": "AUTONOMOUS", "recent_actions": []}
        self.assertEqual(self.ollama.decide(observation, jpeg()), response())
        body = self.http.call_args.args[2]
        self.assertEqual(body["model"], self.config.model)
        self.assertFalse(body["stream"])
        self.assertEqual(body["format"]["properties"]["duration"]["maximum"], self.config.max_action_duration)
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(json.loads(body["messages"][1]["content"]), observation)
        self.assertEqual(len(body["messages"][1]["images"]), 1)

    def test_model_errors_revoke_verification_and_busy_is_rejected(self):
        with self.assertRaises(OllamaError):
            self.ollama.decide({}, jpeg())
        self.ollama.verified = True
        self.http.side_effect = TimeoutError("slow")
        with self.assertRaises(TimeoutError):
            self.ollama.decide({}, jpeg())
        self.assertFalse(self.ollama.verified)
        self.ollama.lock.acquire()
        try:
            self.assertFalse(self.ollama.test())
            self.assertIn("already busy", self.ollama.status["result"])
        finally:
            self.ollama.lock.release()

    def test_real_urllib_against_local_http_stub_success_and_errors(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200 if self.path != "/error" else 500)
                self.end_headers()
                self.wfile.write(b'{"done":true,"message":{"content":"hi"}}' if self.path == "/ok" else b"malformed")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            result = JsonHTTP()("POST", base + "/ok", {"model": "test", "stream": False}, 1)
            self.assertEqual(Ollama.content(result), "hi")
            self.assertEqual(requests[0], {"model": "test", "stream": False})
            for path in ("/bad", "/error"):
                with self.subTest(path=path), self.assertRaises(OllamaError):
                    JsonHTTP()("POST", base + path, {}, 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
