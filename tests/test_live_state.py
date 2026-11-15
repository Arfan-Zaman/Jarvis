import json
import unittest

from jarvis.providers.scripted import ScriptedProvider
from jarvis.safety import ActionCategory
from jarvis.tools import Tool
from support import JarvisTestCase


def plan(*steps):
    return {"plan": [{"description": d, "tool": t} for d, t in steps]}


class LiveStateTests(JarvisTestCase):
    def scripted(self, replies):
        self.app = self.make_app(provider=ScriptedProvider(replies))
        return self.app

    def test_calm_when_nothing_has_happened(self):
        self.assertEqual(self.app.engine.live()["state"], "calm")

    def test_states_follow_a_real_run(self):
        seen = []

        def watch(messages):
            seen.append(self.app.engine.live())          # observe mid-run, as the interface would
            return {"inputs": {"title": "Call Sam"}}

        app = self.scripted([plan(("Create the task", "tasks.create")), watch, {"achieved": True, "summary": "x"}])
        app.engine.start("Add a task")
        self.assertEqual(seen[0]["state"], "planning")
        self.assertEqual(seen[0]["plan"][0]["description"], "Create the task")
        done = app.engine.live()
        self.assertEqual(done["state"], "success")
        self.assertEqual(done["activity"][0]["status"], "succeeded")

    def test_failure_concerned_and_resolute(self):
        seen = []

        def bad(messages):
            seen.append(self.app.engine.live()["state"])
            return {"inputs": {"title": "x", "project_id": 999}}

        def retry(messages):
            seen.append(self.app.engine.live()["state"])   # after a failed step: concerned
            return {"inputs": {"title": "x"}}

        app = self.scripted([plan(("Create", "tasks.create")), bad, retry, {"achieved": True, "summary": "x"}])
        app.engine.start("Add a task")
        self.assertEqual(seen, ["planning", "concerned"])
        self.assertEqual(app.engine.live()["state"], "success")

        app = self.scripted([plan(("Create", "tasks.create")), {"inputs": {"title": "x", "project_id": 9}},
                             {"inputs": {"title": "x", "project_id": 9}}])
        app.engine.start("Add a task")
        live = app.engine.live()
        self.assertEqual(live["state"], "failure")
        self.assertIn("failed", live["detail"])

    def test_approval_and_awaiting(self):
        app = self.scripted([plan(("Send", "demo.send")), {"inputs": {"target": "a"}}])
        app.tools.register(Tool("demo.send", "test", ActionCategory.EXTERNAL_COMMUNICATION,
                                lambda a, v, actor: {}, {"target": {"type": "string"}}))
        app.engine.start("Send it")
        self.assertEqual(app.engine.live()["state"], "approval")
        app = self.scripted([{"blocked": "Which one?"}])
        app.engine.start("Do it")
        live = app.engine.live()
        self.assertEqual((live["state"], live["detail"]), ("awaiting", "Which one?"))

    def test_success_fades_back_to_calm(self):
        app = self.scripted([plan(("List", "tasks.list")), {"inputs": {}}, {"achieved": True, "summary": "x"}])
        run = app.engine.start("List tasks")
        self.sql("UPDATE runs SET finished_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (run["run_id"],))
        self.assertEqual(app.engine.live()["state"], "calm")


if __name__ == "__main__":
    unittest.main()
