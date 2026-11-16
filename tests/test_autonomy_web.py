import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from jarvis.common import PermissionDenied
from jarvis.providers.scripted import ScriptedProvider
from jarvis.safety import ActionCategory
from jarvis.tools import web
from support import JarvisTestCase

PAGE = """<html><head><title>Test Page</title><style>body{color:red}</style></head>
<body><nav>Menu Home About</nav><h1>Fresh news</h1><p>The answer is <b>42</b>.</p>
<script>alert('x')</script><p>Second &amp; last paragraph.</p><footer>Copyright</footer></body></html>"""


class FakeWeb(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body, content_type="text/html; charset=utf-8", headers=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.server.seen.append((self.path, dict(self.headers)))
        path = self.path.split("?")[0]
        if path == "/page":
            return self.send(200, PAGE)
        if path == "/long":
            return self.send(200, "<p>" + "word " * 5000 + "</p>")
        if path == "/plain":
            return self.send(200, "just text", "text/plain")
        if path == "/image":
            return self.send(200, b"\x89PNG", "image/png")
        if path == "/to-private":
            return self.send(302, "", headers={"Location": f"http://localhost:{self.server.server_port}/page"})
        if path == "/wiki":
            return self.send(200, json.dumps({"pages": [
                {"title": "Python (programming language)", "key": "Python_(programming_language)",
                 "excerpt": 'A <span class="searchmatch">language</span>'}]}), "application/json")
        if path == "/ddg":
            return self.send(200, json.dumps({"Heading": "Python", "AbstractText": "Python is a language.",
                                              "AbstractURL": "https://en.wikipedia.org/wiki/Python_(programming_language)",
                                              "RelatedTopics": [{"Text": "Guido - creator", "FirstURL": "https://duckduckgo.com/Guido"}]}),
                             "application/json")
        if path == "/brave":
            return self.send(200, json.dumps({"web": {"results": [
                {"title": "News", "url": "https://news.example.com/a", "description": "<b>Today</b> it rained"}]}}),
                "application/json")
        return self.send(404, "missing")


class WebCase(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.server = HTTPServer(("127.0.0.1", 0), FakeWeb)
        self.server.seen = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        # Pretend 127.0.0.1 is "the internet" for these tests; "localhost" stays private.
        patcher = mock.patch.object(web, "is_public_host", side_effect=lambda host: host == "127.0.0.1")
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, path in (("WIKIPEDIA_URL", "/wiki"), ("DDG_URL", "/ddg"), ("BRAVE_URL", "/brave")):
            p = mock.patch.object(web, name, self.base + path)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"JARVIS_BRAVE_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)

    def fetch(self, url, **extra):
        return self.app.tools.execute("web.fetch", {"url": url, **extra})


class AutonomyPolicyTests(JarvisTestCase):
    def test_automatic_levels_run_without_asking(self):
        for category in (ActionCategory.READ, ActionCategory.WEB_READ, ActionCategory.WRITE, ActionCategory.WORKSPACE):
            with self.subTest(category=category.value):
                decision = self.app.safety.authorize("x", category, "x")
                self.assertTrue(decision.allowed)
                self.assertFalse(decision.requires_approval)

    def test_the_hard_lines_still_ask(self):
        for category in ("destructive", "external_communication", "financial", "system"):
            with self.subTest(category=category):
                self.assertTrue(self.app.safety.authorize("x", category, "x").requires_approval)

    def test_read_only_mode(self):
        locked = self.make_app(allow_writes="false")
        self.assertTrue(locked.safety.authorize("x", ActionCategory.WEB_READ, "x").allowed)
        with self.assertRaises(PermissionDenied):
            locked.safety.authorize("x", ActionCategory.WORKSPACE, "x")

    def test_workspace_exists_and_is_writable_but_bounded(self):
        workspace = self.app.config.workspace_dir
        self.assertTrue(workspace.is_dir())
        self.assertEqual(self.app.safety.authorize_path(workspace / "a" / "b.py", write=True), workspace / "a" / "b.py")
        for outside in (self.app.config.root / "jarvis" / "x.py", workspace / ".." / "escape.py", "/tmp/x"):
            with self.subTest(path=str(outside)), self.assertRaises(PermissionDenied):
                self.app.safety.authorize_path(outside, write=True)

    def test_policy_is_reported(self):
        policy = self.app.status()["safety"]
        self.assertEqual(policy["automatic"], ["read", "web_read", "write", "workspace"])
        self.assertEqual(policy["approval_required_for"], ["destructive", "external_communication", "financial", "system"])
        self.assertEqual(policy["workspace"], str(self.app.config.workspace_dir))
        specs = {t["name"]: t for t in self.app.tools.list()}
        self.assertFalse(specs["web.search"]["requires_approval"])


class FetchTests(WebCase):
    def test_reads_page_text_without_clutter(self):
        result = self.fetch(self.base + "/page")
        self.assertTrue(result["ok"], result)
        output = result["output"]
        self.assertEqual(output["title"], "Test Page")
        self.assertIn("Fresh news", output["text"])
        self.assertIn("The answer is 42.", output["text"])
        self.assertIn("Second & last paragraph.", output["text"])
        for clutter in ("alert", "color:red", "Menu Home", "Copyright"):
            self.assertNotIn(clutter, output["text"])
        self.assertEqual(result["permission"], "web_read")
        self.assertEqual(self.server.seen[-1][1]["User-Agent"], web.USER_AGENT)

    def test_text_is_capped(self):
        output = self.fetch(self.base + "/long", max_chars=600)["output"]
        self.assertEqual((len(output["text"]), output["truncated"]), (600, True))

    def test_focus_keeps_the_relevant_parts_of_long_pages(self):
        long_page = "<p>" + "filler words here " * 400 + "</p><p>Mount Kosciuszko is 2,228 metres high.</p>" \
                    + "<p>" + "more filler " * 400 + "</p>"
        with mock.patch.object(web, "_get", return_value=(long_page.encode(), "text/html", self.base + "/x")):
            output = self.fetch(self.base + "/x", max_chars=600, focus="tallest mountain Kosciuszko height")["output"]
        self.assertEqual(output["text"], "Mount Kosciuszko is 2,228 metres high.")
        self.assertEqual(output["focused_on"], "tallest mountain Kosciuszko height")

    def test_focus_drops_repeated_lines_and_skips_lines_too_long(self):
        long_page = "<p>" + "mountain " * 200 + "</p>" + "<p>Share this mountain page</p>" * 30 \
                    + "<p>Puncak Jaya is 4,884 metres high, the tallest mountain on the continent.</p>" \
                    + "<p>" + "filler " * 500 + "</p>"
        with mock.patch.object(web, "_get", return_value=(long_page.encode(), "text/html", self.base + "/x")):
            output = self.fetch(self.base + "/x", max_chars=600, focus="tallest mountain height")["output"]
        self.assertEqual(output["text"].splitlines(),
                         ["Share this mountain page",
                          "Puncak Jaya is 4,884 metres high, the tallest mountain on the continent."])

    def test_plain_text_is_read_and_binaries_refused(self):
        self.assertEqual(self.fetch(self.base + "/plain")["output"]["text"], "just text")
        result = self.fetch(self.base + "/image")
        self.assertFalse(result["ok"])
        self.assertIn("image/png", result["error"])

    def test_private_and_non_web_addresses_are_refused(self):
        port = self.server.server_port
        for url in (f"http://localhost:{port}/page", "http://10.0.0.1/", "http://192.168.1.1/", "file:///etc/passwd",
                    "ftp://example.com/", "javascript:alert(1)", "", "not a url"):
            with self.subTest(url=url):
                result = self.fetch(url)
                self.assertFalse(result["ok"])
        self.assertEqual([p for p, _ in self.server.seen], [])        # nothing was requested

    def test_redirect_to_a_private_address_is_refused(self):
        result = self.fetch(self.base + "/to-private")
        self.assertFalse(result["ok"])
        self.assertIn("not a public internet address", result["error"])
        self.assertEqual([p for p, _ in self.server.seen], ["/to-private"])   # the private page was never read

    def test_http_errors_are_reported(self):
        result = self.fetch(self.base + "/missing")
        self.assertFalse(result["ok"])
        self.assertIn("HTTP 404", result["error"])


class PublicHostTests(unittest.TestCase):
    def test_addresses(self):
        def resolves(*addresses):
            return mock.patch.object(web.socket, "getaddrinfo",
                                     return_value=[(0, 0, 0, "", (a, 0)) for a in addresses])
        with resolves("93.184.216.34"):
            self.assertTrue(web.is_public_host("example.com"))
        for private in ("127.0.0.1", "10.1.2.3", "192.168.0.5", "172.16.0.1", "169.254.1.1", "::1", "fe80::1"):
            with self.subTest(address=private), resolves(private):
                self.assertFalse(web.is_public_host("sneaky.example"))
        with resolves("93.184.216.34", "127.0.0.1"):                       # any private address is enough to refuse
            self.assertFalse(web.is_public_host("mixed.example"))
        with mock.patch.object(web.socket, "getaddrinfo", side_effect=web.socket.gaierror):
            self.assertFalse(web.is_public_host("no-such-host.invalid"))


class SearchTests(WebCase):
    def test_keyless_providers(self):
        result = self.app.tools.execute("web.search", {"query": "python language"})
        self.assertTrue(result["ok"], result)
        output = result["output"]
        self.assertEqual(output["searched"], ["wikipedia", "duckduckgo"])
        urls = [r["url"] for r in output["results"]]
        self.assertEqual(urls[0], "https://en.wikipedia.org/wiki/Python_(programming_language)")
        self.assertIn("https://duckduckgo.com/Guido", urls)
        self.assertEqual(output["results"][0]["snippet"], "A language")        # markup removed
        self.assertIn("no full web search", output["note"])

    def test_brave_is_used_when_the_owner_adds_a_key(self):
        with mock.patch.dict(os.environ, {"JARVIS_BRAVE_API_KEY": "test-key"}):
            output = self.app.tools.execute("web.search", {"query": "weather"})["output"]
        self.assertEqual(output["searched"][0], "brave")
        self.assertEqual(output["results"][0], {"title": "News", "url": "https://news.example.com/a",
                                                "snippet": "Today it rained", "source": "brave"})
        self.assertIsNone(output["note"])
        brave_request = next(h for p, h in self.server.seen if p.startswith("/brave"))
        self.assertEqual(brave_request["X-Subscription-Token"], "test-key")

    def test_one_failing_provider_does_not_stop_search(self):
        with mock.patch.object(web, "DDG_URL", self.base + "/missing"):
            output = self.app.tools.execute("web.search", {"query": "python"})["output"]
        self.assertEqual(output["searched"], ["wikipedia"])
        self.assertIn("HTTP 404", output["errors"][0])

    def test_all_providers_failing_is_a_failure(self):
        with mock.patch.object(web, "DDG_URL", self.base + "/missing"), \
                mock.patch.object(web, "WIKIPEDIA_URL", self.base + "/missing"):
            result = self.app.tools.execute("web.search", {"query": "python"})
        self.assertFalse(result["ok"])
        self.assertIn("every search service failed", result["error"])

    def test_blank_query(self):
        self.assertFalse(self.app.tools.execute("web.search", {"query": "   "})["ok"])


class ChatWebTests(WebCase):
    def test_web_answer_cites_the_sources_actually_used(self):
        self.model = ScriptedProvider([
            {"mode": "act", "goal": "Find out what the answer is on the test page"},
            {"plan": [{"description": "Read the page", "tool": "web.fetch"}]},
            {"inputs": {"url": self.base + "/page"}},
            {"achieved": True, "summary": "The answer is 42."},
            "The page says the answer is 42. See https://made-up.example for more.",
        ])
        self.app = self.make_app(provider=self.model)
        reply = self.app.chat("What does the test page say?")["reply"]
        self.assertTrue(reply["content"].endswith(f"Sources: {self.base}/page"))
        self.assertIn("If the goal contains a web address", self.model.prompts[1][0].content)
        self.assertNotIn("Sources: https://made-up", reply["content"])
        report = self.app.engine.report(reply["run_id"])
        self.assertEqual(report["changes_made"], [])                   # reading the web changes nothing
        self.assertIn("web.search", self.model.prompts[0][0].content)  # routing knows the web exists
        self.assertIn("The answer is 42.", self.model.prompts[-1][0].content)


if __name__ == "__main__":
    unittest.main()
