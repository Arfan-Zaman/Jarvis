"""Phone access: loopback stays the only listener; outside requests need the access code."""

import http.client
import json
import threading
import unittest

from jarvis.__main__ import _write_env_values
from jarvis.config import ConfigError
from jarvis.web import create_server
from jarvis.web import server as web
from support import JarvisTestCase, make_config

HOST = "my-mac.tail1234.ts.net"
TOKEN = "t" * 32


class RemoteConfigTests(JarvisTestCase):
    def test_off_by_default(self):
        self.assertFalse(make_config(self.root).remote_enabled)

    def test_needs_host_and_long_code_together(self):
        for overrides in ({"remote_host": HOST}, {"access_token": TOKEN},
                          {"remote_host": HOST, "access_token": "short"},
                          {"remote_host": "https://x.ts.net", "access_token": TOKEN},
                          {"remote_host": "localhost", "access_token": TOKEN}):
            with self.subTest(overrides=overrides), self.assertRaises(ConfigError):
                make_config(self.root, **overrides)
        self.assertTrue(make_config(self.root, remote_host=HOST.upper() + ".", access_token=TOKEN).remote_enabled)

    def test_token_never_shown(self):
        config = make_config(self.root, remote_host=HOST, access_token=TOKEN)
        self.assertNotIn(TOKEN, json.dumps(config.public_dict()))

    def test_env_writer_keeps_other_lines(self):
        path = self.root / "x.env"
        path.write_text("# hi\nJARVIS_PORT=9000\nJARVIS_REMOTE_HOST=old\n")
        _write_env_values(path, {"JARVIS_REMOTE_HOST": HOST, "JARVIS_ACCESS_TOKEN": TOKEN})
        self.assertEqual(path.read_text(),
                         f"# hi\nJARVIS_PORT=9000\nJARVIS_REMOTE_HOST={HOST}\nJARVIS_ACCESS_TOKEN={TOKEN}\n")


class RemoteWebTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(remote_host=HOST, access_token=TOKEN)
        self.server = create_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            send = {"Content-Type": "application/json"} if body is not None else {}
            send.update(headers or {})
            conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=send)
            response = conn.getresponse()
            raw = response.read()
            return response.status, raw, response
        finally:
            conn.close()

    def outside(self, **extra):
        return {"Host": HOST, "X-Forwarded-For": "100.64.0.9", **extra}

    def login(self, code=TOKEN):
        return self.call("POST", "/api/login", {"code": code}, self.outside(Origin=f"https://{HOST}"))

    def cookie(self):
        status, _, response = self.login()
        self.assertEqual(status, 200)
        header = response.getheader("Set-Cookie")
        for flag in ("HttpOnly", "Secure", "SameSite=Strict"):
            self.assertIn(flag, header)
        return {"Cookie": header.split(";")[0]}

    def test_this_mac_needs_no_login(self):
        self.assertEqual(self.call("GET", "/api/status")[0], 200)
        self.assertEqual(self.call("GET", "/")[0], 200)

    def test_outside_is_locked_until_login(self):
        status, _, response = self.call("GET", "/", headers=self.outside())
        self.assertEqual((status, response.getheader("Location")), (302, "/login"))
        for path in ("/api/status", "/api/memories", "/static/app.js", "/static/os.html"):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path, headers=self.outside())[0], 401 if path.startswith("/api") else 302)
        self.assertEqual(self.call("POST", "/api/memories", {"content": "x"}, self.outside())[0], 401)

    def test_login_page_and_install_files_are_public(self):
        for path in ("/login", "/manifest.webmanifest", "/static/login.js", "/static/login.css",
                     "/static/icons/apple-touch-icon.png", "/static/icons/icon-192.png"):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path, headers=self.outside())[0], 200)
        _, raw, _ = self.call("GET", "/manifest.webmanifest", headers=self.outside())
        self.assertEqual(json.loads(raw)["display"], "standalone")

    def test_wrong_code_refused_and_right_code_unlocks(self):
        self.assertEqual(self.login("wrong")[0], 401)
        cookie = self.cookie()
        status, raw, _ = self.call("GET", "/api/status", headers=self.outside(**cookie))
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/", headers=self.outside(**cookie))[0], 200)
        self.assertEqual(self.call("GET", "/login", headers=self.outside(**cookie))[0], 302)
        status, _, _ = self.call("POST", "/api/memories", {"content": "from phone"},
                                 self.outside(Origin=f"https://{HOST}", **cookie))
        self.assertEqual(status, 201)

    def test_forged_cookie_and_changed_code_refused(self):
        self.assertEqual(self.call("GET", "/api/status", headers=self.outside(Cookie="jarvis_session=nope"))[0], 401)
        cookie = self.cookie()
        self.app.config = make_config(self.root, remote_host=HOST, access_token="n" * 32)
        self.assertEqual(self.call("GET", "/api/status", headers=self.outside(**cookie))[0], 401)

    def test_localhost_host_header_through_the_proxy_still_needs_login(self):
        spoof = {"Host": "127.0.0.1", "X-Forwarded-For": "100.64.0.9"}
        self.assertEqual(self.call("GET", "/api/status", headers=spoof)[0], 401)

    def test_other_hosts_and_origins_still_refused(self):
        cookie = self.cookie()
        self.assertEqual(self.call("GET", "/api/status", headers={"Host": "evil.example", **cookie})[0], 403)
        status, _, _ = self.call("POST", "/api/memories", {"content": "x"},
                                 self.outside(Origin="https://evil.example", **cookie))
        self.assertEqual(status, 403)

    def test_guessing_is_throttled(self):
        for _ in range(web.MAX_LOGIN_FAILURES):
            self.assertEqual(self.login("wrong")[0], 401)
        self.assertEqual(self.login()[0], 429)          # even the right code waits out the lock

    def test_logout_clears_cookie(self):
        cookie = self.cookie()
        _, _, response = self.call("POST", "/api/logout", {}, self.outside(Origin=f"https://{HOST}", **cookie))
        self.assertIn("Max-Age=0", response.getheader("Set-Cookie"))


class RemoteDisabledTests(JarvisTestCase):
    def test_outside_hosts_refused_when_phone_access_is_off(self):
        server = create_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        conn.request("GET", "/api/status", headers={"Host": HOST})
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()


if __name__ == "__main__":
    unittest.main()
