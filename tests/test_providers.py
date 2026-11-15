import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from jarvis.providers import (
    AIProvider, ChatMessage, NullProvider, ProviderError, ProviderResponse, ProviderStatus, build_provider,
)
from jarvis.providers.ollama import OllamaProvider
from support import JarvisTestCase, make_config


class EchoProvider(AIProvider):
    """A stand-in model for tests. Never used outside the test suite."""

    name = "echo"

    def __init__(self, fail=False):
        self.fail = fail
        self.seen = []

    def status(self):
        return ProviderStatus("echo", "local", True, True, "echo-1", "test provider")

    def generate(self, messages):
        self.seen = messages
        if self.fail:
            raise ProviderError("model crashed")
        return ProviderResponse(f"echo: {messages[-1].content}", "echo", "echo-1")


class FakeOllama(BaseHTTPRequestHandler):
    """Imitates the two Ollama endpoints JARVIS uses."""

    def log_message(self, *args):
        pass

    def _reply(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply({"models": [{"name": "tiny:latest"}]})

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(request)
        self._reply({"message": {"role": "assistant", "content": " hello from fake "}})


class NoProviderTests(JarvisTestCase):
    def test_default_is_no_provider_and_it_says_so(self):
        status = self.app.status()["ai"]
        self.assertEqual(status["name"], "none")
        self.assertFalse(status["configured"])
        self.assertFalse(status["available"])
        self.assertIn("No AI provider is configured", status["detail"])

    def test_null_provider_never_generates(self):
        with self.assertRaises(ProviderError):
            NullProvider().generate([ChatMessage("user", "hi")])

    def test_chat_without_a_model_does_not_fake_a_reply(self):
        result = self.app.chat("Are you there?")
        self.assertEqual(result["reply"]["role"], "system")
        self.assertIn("No AI model is connected", result["reply"]["content"])
        messages = self.app.get("conversations", result["conversation"]["id"])["messages"]
        self.assertEqual([m["role"] for m in messages], ["user", "system"])
        self.assertEqual(messages[0]["content"], "Are you there?")
        self.assertNotIn("assistant", [m["role"] for m in messages])

    def test_unknown_and_unimplemented_providers_report_clearly(self):
        unknown = build_provider(make_config(self.root, ai_provider="skynet")).status()
        self.assertFalse(unknown.configured)
        self.assertIn("Unknown AI provider 'skynet'", unknown.detail)
        mlx = build_provider(make_config(self.root, ai_provider="mlx")).status()
        self.assertFalse(mlx.configured)
        self.assertIn("not implemented", mlx.detail)

    def test_external_provider_is_blocked_unless_allowed(self):
        class Remote(EchoProvider):
            is_local = False

        from jarvis.providers import registry
        registry.register_provider("remote-test", lambda config: Remote())
        self.addCleanup(registry._FACTORIES.pop, "remote-test")
        blocked = build_provider(make_config(self.root, ai_provider="remote-test"))
        self.assertIsInstance(blocked, NullProvider)
        allowed = build_provider(make_config(self.root, ai_provider="remote-test", allow_external_ai="true"))
        self.assertIsInstance(allowed, Remote)

    def test_remote_ollama_address_counts_as_external(self):
        provider = build_provider(make_config(self.root, ai_provider="ollama", ai_model="m",
                                              ollama_url="http://203.0.113.5:11434"))
        self.assertIsInstance(provider, NullProvider)
        self.assertIn("not on this machine", provider.status().detail)


class ConnectedProviderTests(JarvisTestCase):
    def test_chat_uses_the_provider_and_labels_the_reply(self):
        provider = EchoProvider()
        app = self.make_app(provider=provider)
        first = app.chat("one")
        self.assertEqual(first["reply"]["role"], "assistant")
        self.assertEqual(first["reply"]["content"], "echo: one")
        self.assertEqual(first["reply"]["provider"], "echo")
        self.assertEqual(first["reply"]["model"], "echo-1")
        app.chat("two", first["conversation"]["id"])
        self.assertEqual([m.role for m in provider.seen], ["system", "user", "assistant", "user"])

    def test_provider_failure_is_reported_not_hidden(self):
        app = self.make_app(provider=EchoProvider(fail=True))
        result = app.chat("hello")
        self.assertEqual(result["reply"]["role"], "system")
        self.assertIn("model crashed", result["reply"]["content"])
        self.assertEqual(app.events.list(category="ai")[0]["level"], "error")

    def test_empty_message_is_rejected(self):
        from jarvis.common import ValidationError
        with self.assertRaises(ValidationError):
            self.app.chat("   ")


class OllamaAdapterTests(unittest.TestCase):
    """Exercises the adapter against a fake server. Real Ollama is untested."""

    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), FakeOllama)
        self.server.requests = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def test_status_and_generate(self):
        provider = OllamaProvider(self.url, "tiny", timeout=5)
        status = provider.status()
        self.assertTrue(status.configured and status.available)
        response = provider.generate([ChatMessage("user", "hi")])
        self.assertEqual(response.text, "hello from fake")
        self.assertEqual(self.server.requests[0]["model"], "tiny")
        self.assertFalse(self.server.requests[0]["stream"])

    def test_missing_model_is_reported(self):
        status = OllamaProvider(self.url, "absent", timeout=5).status()
        self.assertFalse(status.available)
        self.assertIn("not installed", status.detail)
        self.assertFalse(OllamaProvider(self.url, "", timeout=5).status().configured)

    def test_unreachable_server_is_reported(self):
        provider = OllamaProvider("http://127.0.0.1:9", "tiny", timeout=2)
        self.assertFalse(provider.status().available)
        with self.assertRaises(ProviderError):
            provider.generate([ChatMessage("user", "hi")])


if __name__ == "__main__":
    unittest.main()
