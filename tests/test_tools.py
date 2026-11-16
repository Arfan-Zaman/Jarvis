import http.client
import json
import sqlite3
import threading
import unittest

from jarvis.common import NotFoundError, ValidationError
from jarvis.db import MIGRATIONS, SCHEMA_VERSION
from jarvis.safety import ActionCategory
from jarvis.tools import Tool
from jarvis.web import create_server
from support import JarvisTestCase

EXPECTED_TOOLS = {
    "claude.work": "workspace", "claude.operate": "system", "claude.research": "web_read", "claude.converse": "web_read", "mac.find_files": "read", "mac.status": "read", "mac.open": "write", "mac.notify": "write", "claude.browse": "system",
    "schedule.add": "write", "schedule.list": "read", "schedule.cancel": "write",
    "mail.recent": "read", "mail.search": "read", "mail.read": "read", "mail.draft": "write",
    "mail.send": "external_communication", "calendar.today": "read", "calendar.upcoming": "read",
    "calendar.add_event": "write",
    "jarvis.info": "read", "system.health": "read", "projects.list": "read", "projects.get": "read",
    "tasks.list": "read", "memory.search": "read",
    "tasks.create": "write", "tasks.update": "write", "tasks.complete": "write",
    "memory.save": "write", "experience.record": "write",
    "web.search": "web_read", "web.fetch": "web_read",
    "image.quote": "web_read", "image.generate": "financial",
}


class ToolCase(JarvisTestCase):
    def run_tool(self, name, inputs=None, **options):
        return self.app.tools.execute(name, inputs, **options)

    def ok(self, name, inputs=None, **options):
        result = self.run_tool(name, inputs, **options)
        self.assertTrue(result["ok"], result)
        return result["output"]

    def add_test_tool(self, name, category, handler=None):
        calls = []

        def default(app, inputs, actor):
            calls.append(inputs)
            return {"did": name, **inputs}

        self.app.tools.register(Tool(name, "A tool used only by tests.", category, handler or default,
                                     {"target": {"type": "string"}}))
        return calls


class RegistryTests(ToolCase):
    def test_builtin_tools_are_discoverable(self):
        tools = {tool["name"]: tool for tool in self.app.tools.list()}
        self.assertEqual({name: tool["permission"] for name, tool in tools.items()}, EXPECTED_TOOLS)
        for tool in tools.values():
            self.assertTrue(tool["description"])
            self.assertIsInstance(tool["inputs"], dict)
            # Only Claude Code with a shell, the browser, spending picture credits and sending email ask first.
            self.assertEqual(tool["requires_approval"],
                             tool["name"] in ("claude.operate", "claude.browse", "image.generate", "mail.send"))
        self.assertEqual(tools["tasks.create"]["inputs"]["title"], {
            "type": "string", "description": "What needs doing.", "required": True})
        self.assertEqual({t["name"] for t in self.app.tools.list("write")},
                         {n for n, p in EXPECTED_TOOLS.items() if p == "write"})

    def test_no_shell_or_code_execution_tool_exists(self):
        for name in self.app.tools.names():
            for word in ("shell", "exec", "command", "eval", "python", "bash"):
                self.assertNotIn(word, name)

    def test_adding_a_tool(self):
        self.add_test_tool("demo.echo", ActionCategory.READ)
        self.assertEqual(self.ok("demo.echo", {"target": "x"}), {"did": "demo.echo", "target": "x"})
        self.assertIn("demo.echo", self.app.tools.names())

    def test_bad_registrations_are_rejected(self):
        fn = lambda app, inputs, actor: None
        bad = (
            Tool("Bad Name", "d", ActionCategory.READ, fn),
            Tool("tasks.create", "duplicate", ActionCategory.READ, fn),
            Tool("demo.nodesc", "  ", ActionCategory.READ, fn),
            Tool("demo.nocat", "d", "read", fn),
            Tool("demo.nohandler", "d", ActionCategory.READ, None),
            Tool("demo.badschema", "d", ActionCategory.READ, fn, {"x": {"type": "list"}}),
            Tool("demo.badkey", "d", ActionCategory.READ, fn, {"x": {"type": "string", "pattern": "."}}),
        )
        for tool in bad:
            with self.subTest(tool=tool.name), self.assertRaises(ValidationError):
                self.app.tools.register(tool)
        with self.assertRaises(NotFoundError):
            self.app.tools.get("nope")


class BuiltinToolTests(ToolCase):
    def test_info_and_health(self):
        info = self.ok("jarvis.info")
        self.assertEqual(info["name"], "JARVIS")
        self.assertFalse(info["ai_connected"])
        self.assertEqual(set(info["tools"]), set(EXPECTED_TOOLS))
        health = self.ok("system.health")
        self.assertFalse(health["healthy"])
        self.assertEqual(health["problems"], ["no backups exist yet"])
        self.app.create_backup()
        self.assertTrue(self.ok("system.health")["healthy"])

    def test_projects(self):
        self.assertEqual([p["name"] for p in self.ok("projects.list")], ["Aureus Detailing", "Monsoor Motors"])
        project = self.ok("projects.get", {"name": "Monsoor Motors"})
        self.assertEqual(project["description"], "Business workspace.")
        self.assertEqual((project["open_tasks"], project["memory_count"]), ([], 0))
        self.ok("tasks.create", {"title": "Linked", "project_id": project["id"]})
        self.assertEqual(len(self.ok("projects.get", {"id": project["id"]})["open_tasks"]), 1)
        self.assertFalse(self.run_tool("projects.get", {"name": "Nope"})["ok"])
        self.assertFalse(self.run_tool("projects.get")["ok"])

    def test_task_tools(self):
        task = self.ok("tasks.create", {"title": "Check stock", "priority": "high"})
        self.assertEqual((task["status"], task["priority"], task["source"]), ("pending", "high", "user"))
        self.ok("tasks.create", {"title": "Other thing"})
        self.assertEqual([t["title"] for t in self.ok("tasks.list", {"query": "stock"})], ["Check stock"])
        self.assertEqual(len(self.ok("tasks.list", {"priority": "high"})), 1)
        self.assertEqual(len(self.ok("tasks.list", {"limit": 1})), 1)

        updated = self.ok("tasks.update", {"id": task["id"], "status": "in_progress", "title": "Check all stock"})
        self.assertEqual((updated["status"], updated["title"]), ("in_progress", "Check all stock"))
        done = self.ok("tasks.complete", {"id": task["id"], "lesson": "Count weekly"})
        self.assertEqual(done["task"]["status"], "completed")
        self.assertEqual(done["experience"]["lesson"], "Count weekly")
        self.assertEqual(len(self.ok("tasks.list", {"status": "completed"})), 1)

    def test_memory_and_experience_tools(self):
        saved = self.ok("memory.save", {"content": "Gate code changes monthly", "category": "premises",
                                        "confidence": 0.7}, actor="agent:test")
        self.assertEqual(saved["source"], "agent:test")          # provenance is the real caller
        self.assertEqual(saved["verification_status"], "unverified")
        self.assertEqual(saved["confidence"], 0.7)
        self.assertEqual([m["id"] for m in self.ok("memory.search", {"query": "gate"})], [saved["id"]])
        self.assertEqual(self.ok("memory.search", {"category": "other"}), [])
        experience = self.ok("experience.record", {"title": "Tried it", "outcome": "mixed", "lesson": "Plan more"})
        self.assertEqual(experience["outcome"], "mixed")

    def test_write_tools_are_audited(self):
        self.ok("tasks.create", {"title": "Audited"}, actor="agent:test")
        event = self.app.events.list(category="audit")[0]
        self.assertEqual((event["action"], event["actor"]), ("task.create", "agent:test"))


class ExecutionEngineTests(ToolCase):
    def test_structured_result(self):
        result = self.run_tool("tasks.create", {"title": "Shape"})
        self.assertEqual(set(result), {"ok", "status", "tool", "permission", "output", "error", "approval",
                                       "run_id", "step_id", "duration_ms"})
        self.assertEqual((result["ok"], result["status"], result["permission"], result["error"]),
                         (True, "succeeded", "write", None))

    def test_invalid_inputs_fail_without_side_effects(self):
        cases = (
            ("tasks.create", {}),                                    # missing required
            ("tasks.create", {"title": 5}),                          # wrong type
            ("tasks.create", {"title": "x", "bogus": 1}),            # unknown input
            ("tasks.create", {"title": "x", "priority": "asap"}),    # not in enum
            ("tasks.create", {"title": "x", "project_id": True}),    # bool is not an integer
            ("tasks.create", {"title": "x", "project_id": "1"}),
            ("tasks.create", "title=x"),                             # not an object
            ("tasks.create", {"title": "   "}),                      # rejected by the store
            ("tasks.create", {"title": "x", "project_id": 999}),     # no such project
            ("tasks.update", {"id": 1}),                             # nothing to change
            ("tasks.update", {"id": 999, "title": "x"}),             # no such task
            ("memory.save", {"content": "x", "confidence": 7}),
        )
        for name, inputs in cases:
            with self.subTest(name=name, inputs=inputs):
                result = self.run_tool(name, inputs)
                self.assertEqual((result["ok"], result["status"]), (False, "failed"))
                self.assertTrue(result["error"])
                self.assertIsNone(result["output"])
        self.assertEqual(self.app.list("tasks"), [])
        self.assertEqual(self.app.list("memories"), [])

    def test_unknown_tool_is_refused(self):
        result = self.run_tool("shell.run", {"command": "rm -rf /"})
        self.assertEqual((result["ok"], result["status"]), (False, "refused"))
        self.assertIn("Unknown tool", result["error"])
        self.assertEqual(self.app.events.list(category="audit")[0]["level"], "warning")

    def test_allow_list_blocks_unauthorised_tools(self):
        allowed = ["tasks.list"]
        self.assertTrue(self.run_tool("tasks.list", actor="agent:reader", allowed=allowed)["ok"])
        result = self.run_tool("tasks.create", {"title": "x"}, actor="agent:reader", allowed=allowed)
        self.assertEqual(result["status"], "refused")
        self.assertIn("not permitted", result["error"])
        self.assertEqual(self.app.list("tasks"), [])

    def test_a_crashing_tool_is_contained(self):
        def explode(app, inputs, actor):
            raise RuntimeError("kaboom")

        self.add_test_tool("demo.crash", ActionCategory.READ, explode)
        result = self.run_tool("demo.crash")
        self.assertEqual((result["ok"], result["status"], result["error"]), (False, "failed", "RuntimeError: kaboom"))
        self.assertTrue(self.ok("jarvis.info"))                    # JARVIS still works

    def test_read_only_mode_allows_reads_and_refuses_writes(self):
        locked = self.make_app(allow_writes="false")
        self.assertTrue(locked.tools.execute("tasks.list")["ok"])
        result = locked.tools.execute("tasks.create", {"title": "x"})
        self.assertEqual(result["status"], "refused")
        self.assertIn("read-only", result["error"])
        self.assertEqual(locked.list("tasks"), [])

    def test_sensitive_tools_wait_for_human_approval(self):
        for number, category in enumerate((ActionCategory.DESTRUCTIVE, ActionCategory.EXTERNAL_COMMUNICATION,
                                           ActionCategory.FINANCIAL, ActionCategory.SYSTEM)):
            with self.subTest(category=category.value):
                name = f"demo.sensitive{number}"
                calls = self.add_test_tool(name, category)
                self.assertTrue(self.app.tools.get(name).spec()["requires_approval"])
                first = self.run_tool(name, {"target": "a"}, actor="agent:test")
                self.assertEqual((first["ok"], first["status"]), (False, "approval_required"))
                self.assertEqual(calls, [])                                    # nothing ran
                self.assertEqual(self.app.runs.get(first["run_id"])["status"], "waiting_approval")
                approval = first["approval"]["id"]

                unapproved = self.run_tool(name, {"target": "a"}, actor="agent:test", approval_id=approval)
                self.assertEqual(unapproved["status"], "refused")
                self.assertEqual(calls, [])

                self.app.safety.approve(approval)
                other = self.run_tool(name, {"target": "b"}, actor="agent:test", approval_id=approval)
                self.assertEqual(other["status"], "refused")                  # approval is for target "a" only
                done = self.run_tool(name, {"target": "a"}, actor="agent:test", approval_id=approval,
                                     run_id=first["run_id"])
                self.assertTrue(done["ok"])
                self.assertEqual(calls, [{"target": "a"}])
                self.assertEqual(self.app.runs.get(first["run_id"])["status"], "completed")

                again = self.run_tool(name, {"target": "a"}, actor="agent:test", approval_id=approval)
                self.assertEqual(again["status"], "refused")                  # single use
                self.assertEqual(len(calls), 1)

    def test_denied_approval_blocks_the_tool(self):
        calls = self.add_test_tool("demo.pay", ActionCategory.FINANCIAL)
        first = self.run_tool("demo.pay", {"target": "a"})
        self.app.safety.deny(first["approval"]["id"])
        self.assertEqual(self.run_tool("demo.pay", {"target": "a"}, approval_id=first["approval"]["id"])["status"],
                         "refused")
        self.assertEqual(calls, [])


class RunLogTests(ToolCase):
    def test_every_execution_is_recorded(self):
        self.add_test_tool("demo.crash", ActionCategory.READ, lambda app, inputs, actor: 1 / 0)
        self.add_test_tool("demo.send", ActionCategory.EXTERNAL_COMMUNICATION)
        outcomes = [
            self.run_tool("tasks.create", {"title": "Logged"}, actor="agent:test"),
            self.run_tool("tasks.create", {}),
            self.run_tool("nope.tool"),
            self.run_tool("demo.crash"),
            self.run_tool("demo.send", {"target": "x"}),
        ]
        history = self.app.runs.history()
        self.assertEqual([step["status"] for step in reversed(history)],
                         ["succeeded", "failed", "refused", "failed", "waiting_approval"])
        self.assertEqual(self.app.runs.count_steps(), 5)

        first = history[-1]
        self.assertEqual((first["tool"], first["actor"], first["category"]), ("tasks.create", "agent:test", "write"))
        self.assertEqual(first["input"], {"title": "Logged"})
        self.assertEqual(first["output"]["title"], "Logged")
        self.assertIsNone(first["error"])
        self.assertTrue(first["started_at"] <= first["finished_at"])
        self.assertGreaterEqual(first["duration_ms"], 0)
        self.assertIn("required", history[-2]["error"])
        self.assertIn("ZeroDivisionError", history[1]["error"])
        self.assertEqual(history[0]["approval_id"], outcomes[4]["approval"]["id"])

        self.assertEqual([step["tool"] for step in self.app.runs.history(tool="demo.crash")], ["demo.crash"])
        self.assertEqual(len(self.app.runs.history(status="failed")), 2)
        self.assertEqual(len(self.app.runs.history(limit=2)), 2)

    def test_runs_are_retrievable(self):
        result = self.run_tool("tasks.create", {"title": "Find me"})
        run = self.app.runs.get(result["run_id"])
        self.assertEqual((run["status"], run["kind"], run["goal"]), ("completed", "tool", "Tool call: tasks.create"))
        self.assertEqual(run["result"]["title"], "Find me")
        self.assertEqual([step["id"] for step in run["steps"]], [result["step_id"]])
        self.assertTrue(run["finished_at"])
        failed = self.run_tool("tasks.create", {})
        self.assertEqual(self.app.runs.get(failed["run_id"])["status"], "failed")
        self.assertEqual([r["id"] for r in self.app.runs.list()], [failed["run_id"], result["run_id"]])
        self.assertEqual(len(self.app.runs.list(status="failed")), 1)
        with self.assertRaises(NotFoundError):
            self.app.runs.get(999)

    def test_the_log_survives_a_restart(self):
        self.run_tool("tasks.create", {"title": "Durable"})
        self.assertEqual(self.make_app().runs.history()[0]["input"], {"title": "Durable"})

    def test_interrupted_runs_are_flagged_on_startup(self):
        run = self.app.runs.create("Long job", kind="goal")
        self.app.announce_startup()
        flagged = self.app.runs.get(run["id"])
        self.assertEqual(flagged["status"], "interrupted")
        self.assertTrue(flagged["finished_at"])
        self.assertEqual(self.app.events.list(limit=1)[0]["action"], "runs.interrupted")


class UpgradeTests(JarvisTestCase):
    def test_version_1_database_is_backed_up_then_upgraded(self):
        path = self.app.config.db_path
        self.app.create("memories", {"content": "from version 1"})
        path.unlink()
        for extra in ("-wal", "-shm"):
            path.with_name(path.name + extra).unlink(missing_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript(f"BEGIN;{MIGRATIONS[0]}PRAGMA user_version = 1;COMMIT;")
        conn.execute("INSERT INTO memories (content, created_at, updated_at) VALUES ('old data', 'n', 'n')")
        conn.commit()
        conn.close()

        upgraded = self.make_app()
        self.assertEqual(upgraded.db.version(), SCHEMA_VERSION)
        self.assertEqual([m["content"] for m in upgraded.list("memories")], ["old data"])
        self.assertTrue(upgraded.tools.execute("tasks.list")["ok"])
        backups = upgraded.backups.list()
        self.assertEqual([b["label"] for b in backups], ["pre-upgrade-v1"])
        # A version 1 backup is still recognised and restorable.
        self.assertTrue(upgraded.backups.verify(upgraded.config.backup_dir / backups[0]["name"]))


class ToolApiTests(ToolCase):
    def setUp(self):
        super().setUp()
        self.server = create_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            conn.request(method, path, body=json.dumps(body) if body is not None else None,
                         headers={"Content-Type": "application/json"} if body is not None else {})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_discover_execute_and_read_history(self):
        status, tools = self.call("GET", "/api/tools")
        self.assertEqual((status, len(tools["items"])), (200, len(EXPECTED_TOOLS)))
        self.assertEqual(len(self.call("GET", "/api/tools?permission=read")[1]["items"]), 14)   # + mac, schedule, mail and calendar reads

        status, result = self.call("POST", "/api/tools/tasks.create/execute", {"inputs": {"title": "Via API"}})
        self.assertEqual((status, result["ok"]), (200, True))
        status, bad = self.call("POST", "/api/tools/tasks.create/execute", {"inputs": {}})
        self.assertEqual((status, bad["status"]), (200, "failed"))
        self.assertEqual(self.call("POST", "/api/tools/nope/execute", {})[1]["status"], "refused")

        self.assertEqual(self.call("GET", f"/api/runs/{result['run_id']}")[1]["steps"][0]["tool"], "tasks.create")
        self.assertEqual(len(self.call("GET", "/api/runs")[1]["items"]), 3)
        self.assertEqual(len(self.call("GET", "/api/executions?status=succeeded")[1]["items"]), 1)
        self.assertEqual(self.call("GET", "/api/runs/999")[0], 404)

    def test_sensitive_tool_over_the_api(self):
        calls = self.add_test_tool("demo.send", ActionCategory.EXTERNAL_COMMUNICATION)
        path = "/api/tools/demo.send/execute"
        status, first = self.call("POST", path, {"inputs": {"target": "a"}})
        self.assertEqual((status, first["status"], calls), (202, "approval_required", []))
        approval = first["approval"]["id"]
        self.call("POST", f"/api/approvals/{approval}/approve")
        status, done = self.call("POST", path, {"inputs": {"target": "a"}, "approval_id": approval,
                                               "run_id": first["run_id"]})
        self.assertEqual((status, done["ok"], calls), (200, True, [{"target": "a"}]))


if __name__ == "__main__":
    unittest.main()
