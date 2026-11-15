import http.client
import json
import threading
import unittest

from jarvis.web import create_server
from support import JarvisTestCase


class WebTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.server = create_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = json.dumps(body) if body is not None else None
            send = {"Content-Type": "application/json"} if body is not None else {}
            send.update(headers or {})
            conn.request(method, path, body=payload, headers=send)
            response = conn.getresponse()
            raw = response.read()
            if response.getheader("Content-Type", "").startswith("application/json"):
                return response.status, json.loads(raw)
            return response.status, raw.decode("utf-8")
        finally:
            conn.close()

    def test_status_reports_no_ai(self):
        status, data = self.call("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertFalse(data["ai"]["configured"])
        self.assertTrue(data["database"]["integrity_ok"])

    def test_dashboard_and_lists(self):
        status, data = self.call("GET", "/api/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["projects"]), 2)
        for path in ("/api/memories", "/api/tasks", "/api/experiences", "/api/projects", "/api/conversations",
                     "/api/agents", "/api/events", "/api/approvals", "/api/backups"):
            with self.subTest(path=path):
                status, data = self.call("GET", path)
                self.assertEqual(status, 200)
                self.assertIn("items", data)

    def test_memory_lifecycle_including_approved_delete(self):
        status, memory = self.call("POST", "/api/memories", {"content": "via http", "category": "test"})
        self.assertEqual(status, 201)
        path = f"/api/memories/{memory['id']}"
        self.assertEqual(self.call("GET", "/api/memories?q=http")[1]["items"][0]["id"], memory["id"])
        self.assertEqual(self.call("PATCH", path, {"content": "edited"})[1]["content"], "edited")
        self.assertFalse(self.call("POST", path + "/archive")[1]["is_active"])
        self.assertEqual(self.call("GET", "/api/memories")[1]["items"], [])
        self.assertEqual(len(self.call("GET", "/api/memories?active=all")[1]["items"]), 1)

        status, pending = self.call("DELETE", path)
        self.assertEqual(status, 202)
        self.assertEqual(pending["status"], "approval_required")
        self.assertEqual(self.call("GET", path)[0], 200)  # still there

        approval = pending["approval"]["id"]
        self.assertEqual(self.call("DELETE", f"{path}?approval_id={approval}")[0], 403)  # not approved yet
        self.assertEqual(self.call("POST", f"/api/approvals/{approval}/approve")[1]["status"], "approved")
        status, done = self.call("DELETE", f"{path}?approval_id={approval}")
        self.assertEqual((status, done["status"]), (200, "deleted"))
        self.assertEqual(self.call("GET", path)[0], 404)

    def test_task_complete_and_chat(self):
        task = self.call("POST", "/api/tasks", {"title": "http task"})[1]
        done = self.call("POST", f"/api/tasks/{task['id']}/complete", {"lesson": "noted"})[1]
        self.assertEqual(done["task"]["status"], "completed")
        self.assertEqual(done["experience"]["lesson"], "noted")
        self.assertEqual(self.call("POST", f"/api/tasks/{task['id']}/reopen")[1]["status"], "pending")

        status, chat = self.call("POST", "/api/chat", {"message": "hello"})
        self.assertEqual(status, 200)
        self.assertEqual(chat["reply"]["role"], "system")
        conversation = self.call("GET", f"/api/conversations/{chat['conversation']['id']}")[1]
        self.assertEqual(len(conversation["messages"]), 2)

    def test_errors(self):
        self.assertEqual(self.call("POST", "/api/memories", {"content": ""})[0], 400)
        self.assertEqual(self.call("GET", "/api/memories/999")[0], 404)
        self.assertEqual(self.call("GET", "/api/nothing")[0], 404)
        self.assertEqual(self.call("PUT", "/api/memories")[0], 501)
        self.assertEqual(self.call("DELETE", "/api/status")[0], 405)
        self.assertEqual(self.call("GET", "/api/memories?active=perhaps")[0], 400)
        self.assertEqual(self.call("GET", "/api/memories?limit=lots")[0], 400)
        status, _ = self.call("POST", "/api/memories", headers={"Content-Type": "text/plain", "Content-Length": "2"})
        self.assertEqual(status, 400)

    def test_requests_from_other_sites_are_refused(self):
        self.assertEqual(self.call("GET", "/api/status", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("POST", "/api/memories", {"content": "x"},
                                   headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("GET", "/api/memories")[1]["items"], [])
        own_origin = {"Origin": f"http://127.0.0.1:{self.port}"}
        self.assertEqual(self.call("POST", "/api/memories", {"content": "x"}, headers=own_origin)[0], 201)

    def test_static_files(self):
        status, html = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("JARVIS", html)
        self.assertEqual(self.call("GET", "/static/app.js")[0], 200)
        self.assertEqual(self.call("GET", "/static/app.css")[0], 200)
        for path in ("/static/../server.py", "/static/%2e%2e/server.py", "/static/missing.js", "/etc/passwd"):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path)[0], 404)


if __name__ == "__main__":
    unittest.main()
