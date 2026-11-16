import http.client
import json
import sqlite3
import threading
import unittest

from jarvis.common import NotFoundError, PermissionDenied, ValidationError
from jarvis.db import MIGRATIONS, SCHEMA_VERSION
from jarvis.engine.engine import parse_json
from jarvis.providers import ProviderError
from jarvis.providers.scripted import ScriptedProvider
from jarvis.safety import ActionCategory
from jarvis.tools import Tool
from jarvis.web import create_server
from support import JarvisTestCase


def plan(*steps):
    return {"plan": [{"description": description, "tool": tool} for description, tool in steps]}


def inputs(**values):
    return {"inputs": values}


SUMMARY = {"achieved": True, "summary": "All done."}
ONE_TASK = [plan(("Create the task", "tasks.create")), inputs(title="Call the supplier"), SUMMARY]


class EngineCase(JarvisTestCase):
    def scripted(self, replies, **overrides):
        self.model = ScriptedProvider(replies)
        self.app = self.make_app(provider=self.model, **overrides)
        return self.app

    def statuses(self, report):
        return [step["status"] for step in report["plan"]]

    def add_tool(self, name, category, handler=None):
        calls = []

        def default(app, values, actor):
            calls.append(values)
            return {"did": name}

        self.app.tools.register(Tool(name, "Test-only tool.", category, handler or default,
                                     {"target": {"type": "string"}}))
        return calls


class GoalTests(EngineCase):
    def test_simple_one_tool_goal(self):
        app = self.scripted(ONE_TASK)
        report = app.engine.start("Add a task to call the supplier")
        self.assertEqual((report["status"], report["verified_complete"]), ("completed", True))
        self.assertEqual(self.statuses(report), ["completed"])
        self.assertEqual(report["counts"]["succeeded"], 1)
        self.assertEqual(report["model_summary"], "All done.")
        self.assertIn("not", report["model_summary_note"].lower() + " not")
        task = app.list("tasks")[0]
        self.assertEqual((task["title"], task["source"]), ("Call the supplier", "jarvis-core"))
        run = app.runs.get(report["run_id"])
        self.assertEqual((run["kind"], run["actor"], run["status"]), ("goal", "user", "completed"))
        self.assertTrue(run["finished_at"])

    def test_multi_step_goal_runs_in_order_and_sees_results(self):
        app = self.scripted([
            plan(("Find the project", "projects.get"), ("Create the task", "tasks.create"),
                 ("Note it", "memory.save")),
            inputs(name="Monsoor Motors"),
            lambda messages: inputs(title="Stock check", project_id=json.loads(
                json.loads(messages[1].content)["results_so_far"][0]["output"])["id"]),
            inputs(content="A stock check task was created"),
            SUMMARY,
        ])
        report = app.engine.start("Create a stock check task for Monsoor Motors and note it")
        self.assertEqual((report["status"], report["verified_complete"]), ("completed", True))
        self.assertEqual([e["tool"] for e in report["executions"]], ["projects.get", "tasks.create", "memory.save"])
        self.assertEqual([e["plan_position"] for e in report["executions"]], [1, 2, 3])
        project = app.projects.get_by_name("Monsoor Motors")
        self.assertEqual(app.list("tasks")[0]["project_id"], project["id"])
        # The model was shown the tool list and the running state.
        self.assertIn("tasks.create", self.model.prompts[0][0].content)
        self.assertEqual(self.model.json_requests, len(self.model.prompts))   # every engine call asks for JSON
        self.assertEqual(json.loads(self.model.prompts[0][1].content)["request"], "PLAN")

    def test_no_model_means_no_run(self):
        with self.assertRaises(ProviderError) as caught:
            self.app.engine.start("Do something")
        self.assertIn("No AI model is connected", str(caught.exception))
        self.assertEqual(self.app.runs.list(), [])

    def test_empty_goal_and_read_only_mode(self):
        app = self.scripted([])
        with self.assertRaises(ValidationError):
            app.engine.start("   ")
        locked = self.make_app(provider=ScriptedProvider(ONE_TASK), allow_writes="false")
        with self.assertRaises(PermissionDenied):
            locked.engine.start("Add a task")
        self.assertEqual(locked.runs.list(), [])


class FailureTests(EngineCase):
    def test_tool_failure_gets_one_corrected_attempt(self):
        app = self.scripted([plan(("Create the task", "tasks.create")),
                             inputs(title="Bad project", project_id=999),
                             inputs(title="Good task"), SUMMARY])
        report = app.engine.start("Add a task")
        self.assertEqual((report["status"], report["verified_complete"]), ("completed", True))
        self.assertEqual([e["status"] for e in report["executions"]], ["failed", "succeeded"])
        self.assertEqual(report["plan"][0]["attempts"], 2)
        retry = json.loads(self.model.prompts[2][1].content)
        self.assertIn("does not exist", retry["previous_attempt_failed_with"])

    def test_repeated_tool_failure_fails_the_run_honestly(self):
        app = self.scripted([plan(("Create", "tasks.create"), ("Note", "memory.save")),
                             inputs(title="x", project_id=999), inputs(title="x", project_id=998)])
        report = app.engine.start("Add a task and note it")
        self.assertEqual((report["status"], report["verified_complete"]), ("failed", False))
        self.assertEqual(self.statuses(report), ["failed", "pending"])
        self.assertIn("failed 2 time(s)", report["error"])
        self.assertEqual(app.list("tasks"), [])
        self.assertEqual(app.list("memories"), [])           # the later step never ran

    def test_invalid_plans(self):
        bad_plans = (
            "I think we should make a task.",                       # not JSON
            {"plan": []},                                           # empty
            {"plan": "create a task"},                              # wrong shape
            {"steps": []},                                          # wrong key
            plan(("Wipe the disk", "shell.run")),                   # unknown tool
            {"plan": [{"tool": "tasks.create"}]},                   # no description
            plan(*[("Step", "tasks.list")] * 13),                   # over the step limit
            [1, 2, 3],
        )
        for bad in bad_plans:
            with self.subTest(bad=str(bad)[:40]):
                app = self.scripted([bad, bad])
                report = app.engine.start("Do something")
                self.assertEqual((report["status"], report["verified_complete"]), ("failed", False))
                self.assertIn("unusable plan twice", report["error"])
                self.assertEqual((report["plan"], report["executions"]), ([], []))

    def test_invalid_plan_then_valid_plan_recovers(self):
        app = self.scripted(["Sure! Here is my plan."] + ONE_TASK)
        self.assertTrue(app.engine.start("Add a task")["verified_complete"])
        self.assertIn("cannot be used", self.model.prompts[1][-1].content)

    def test_json_is_found_inside_surrounding_text(self):
        self.assertEqual(parse_json('Here you go:\n```json\n{"a": 1}\n```'), {"a": 1})
        for bad in ("nothing", "{not json}", "[1]", None):
            with self.assertRaises(ValueError):
                parse_json(bad)

    def test_invalid_action_inputs_never_reach_the_tool(self):
        app = self.scripted([plan(("Create", "tasks.create")), inputs(bogus=1), {"inputs": "title"}])
        report = app.engine.start("Add a task")
        self.assertEqual(report["status"], "failed")
        self.assertIn("unusable action twice", report["error"])
        self.assertEqual(report["executions"], [])

    def test_inputs_placed_beside_inputs_are_lifted(self):
        for action in ({"title": "Call the supplier"}, {"inputs": {}, "title": "Call the supplier"}):
            with self.subTest(action=action):
                app = self.scripted([plan(("Create the task", "tasks.create")), action, SUMMARY])
                report = app.engine.start("Add a task to call the supplier")
                self.assertEqual(report["status"], "completed")
                self.assertEqual(app.list("tasks")[0]["title"], "Call the supplier")

    def test_stray_keys_are_not_mistaken_for_inputs(self):
        app = self.scripted([plan(("Create", "tasks.create")), {"bogus": 1}, {"thought": "hmm"}])
        report = app.engine.start("Add a task")
        self.assertIn("unusable action twice", report["error"])
        self.assertEqual(report["executions"], [])

    def test_model_error_fails_the_run(self):
        app = self.scripted([plan(("Create", "tasks.create")), ProviderError("model went away")])
        report = app.engine.start("Add a task")
        self.assertEqual(report["status"], "failed")
        self.assertIn("model went away", report["error"])

    def test_refused_tool_stops_the_run(self):
        app = self.scripted([plan(("List", "tasks.list"), ("Create", "tasks.create")), inputs()])
        # tasks.create was planned while permitted, then the permission is withdrawn.
        report = app.engine.start("List then add", allowed=["tasks.list", "tasks.create"])
        self.assertEqual(report["status"], "failed")          # script ran out before step 2: model failure
        app = self.scripted([plan(("Create", "tasks.create")), plan(("Create", "tasks.create"))])
        report = app.engine.start("Add a task", allowed=["tasks.list"])
        self.assertEqual(report["status"], "failed")
        self.assertIn("not an available tool", report["error"])
        self.assertNotIn("tasks.create", self.model.prompts[0][0].content)   # never even offered
        self.assertEqual(app.list("tasks"), [])


class HonestyTests(EngineCase):
    def test_false_completion_claims_are_not_believed(self):
        claims = ({"done": True}, {"final": "I created the task."}, {"summary": "Task created successfully."})
        for claim in claims:
            with self.subTest(claim=claim):
                app = self.scripted([plan(("Create", "tasks.create")), claim, claim])
                report = app.engine.start("Add a task")
                self.assertEqual((report["status"], report["verified_complete"]), ("failed", False))
                self.assertEqual(app.list("tasks"), [])

    def test_model_summary_cannot_override_a_failure(self):
        app = self.scripted([plan(("Create", "tasks.create")), inputs(title="x", project_id=999),
                             inputs(title="x", project_id=999), {"summary": "Everything worked perfectly."}])
        report = app.engine.start("Add a task")
        self.assertEqual((report["status"], report["verified_complete"]), ("failed", False))
        self.assertIsNone(report["model_summary"])
        self.assertIn("Stopped after 0 of 1", report["summary"])

    def test_completion_requires_a_recorded_success_for_every_step(self):
        app = self.scripted(ONE_TASK)
        report = app.engine.start("Add a task")
        # Remove the evidence: the report must no longer call it verified.
        self.sql("DELETE FROM run_steps WHERE run_id = ?", (report["run_id"],))
        self.assertFalse(app.engine.report(report["run_id"])["verified_complete"])

    def test_unconfirmed_goal_is_not_reported_complete(self):
        app = self.scripted(ONE_TASK[:2] + ["no json here", {"summary": "Done!"}])
        report = app.engine.start("Add a task")
        self.assertEqual((report["status"], report["verified_complete"]), ("failed", False))
        self.assertIn("could not confirm", report["error"])
        self.assertEqual(len(app.list("tasks")), 1)          # the work that did happen is still recorded

    def test_lookup_only_plan_is_caught_and_extended(self):
        # The real-model failure: the plan only looked things up, then claimed success.
        app = self.scripted([
            plan(("Find the project", "projects.list")), inputs(),
            {"achieved": False, "missing": "The task was not created",
             "next_steps": [{"description": "Create the task", "tool": "tasks.create"}]},
            inputs(title="Call the parts supplier"),
            SUMMARY,
        ])
        report = app.engine.start("Add a task to call the parts supplier")
        self.assertEqual((report["status"], report["verified_complete"]), ("completed", True))
        self.assertEqual([s["tool"] for s in report["plan"]], ["projects.list", "tasks.create"])
        self.assertEqual(report["changes_made"], [{"tool": "tasks.create",
                                                   "what": f"title: Call the parts supplier (#{app.list('tasks')[0]['id']})"}])
        self.assertIn("1 change(s) made", report["summary"])

    def test_goal_not_achieved_fails_honestly(self):
        app = self.scripted([plan(("Find the project", "projects.list")), inputs(),
                             {"achieved": False, "missing": "Nothing was created", "next_steps": []}])
        report = app.engine.start("Add a task")
        self.assertEqual((report["status"], report["verified_complete"]), ("failed", False))
        self.assertIn("goal was not achieved: Nothing was created", report["error"])
        self.assertEqual(report["changes_made"], [])

    def test_plan_is_extended_only_once(self):
        not_yet = {"achieved": False, "missing": "Still missing",
                   "next_steps": [{"description": "Look again", "tool": "projects.list"}]}
        app = self.scripted([plan(("Look", "projects.list")), inputs(), not_yet, inputs(), not_yet])
        report = app.engine.start("Add a task")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(report["plan"]), 2)
        self.assertIn("Still missing", report["error"])

    def test_review_cannot_add_unknown_tools(self):
        bad = {"achieved": False, "missing": "x", "next_steps": [{"description": "Wipe", "tool": "shell.run"}]}
        app = self.scripted([plan(("Look", "projects.list")), inputs(), bad, bad])
        report = app.engine.start("Add a task")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(report["plan"]), 1)

    def test_read_only_goal_reports_no_changes(self):
        app = self.scripted([plan(("List projects", "projects.list")), inputs(), SUMMARY])
        report = app.engine.start("Which projects do I have?")
        self.assertEqual((report["status"], report["changes_made"]), ("completed", []))
        self.assertIn("no changes were needed or made", report["summary"])

    def test_the_model_is_told_to_ask_rather_than_guess(self):
        app = self.scripted([{"blocked": "Which business: Monsoor Motors or Aureus Detailing?"}])
        report = app.engine.start("Add a task for the business")
        self.assertEqual(report["status"], "blocked")
        protocol = self.model.prompts[0][0].content
        self.assertIn("Never guess which project", protocol)
        self.assertIn("does not by itself add", protocol)


class LimitTests(EngineCase):
    def test_step_limit_is_configurable(self):
        app = self.scripted([plan(("a", "tasks.list"), ("b", "tasks.list"), ("c", "tasks.list"))] * 2,
                            engine_max_steps=2)
        report = app.engine.start("List a lot")
        self.assertEqual(report["status"], "failed")
        self.assertIn("the limit is 2", report["error"])

    def test_failure_limit_stops_the_run(self):
        bad = inputs(title="x", project_id=999)
        app = self.scripted([plan(("a", "tasks.create"), ("b", "tasks.create"))] + [bad] * 4, engine_max_failures=1)
        report = app.engine.start("Add tasks")
        self.assertEqual(report["status"], "failed")
        self.assertIn("limit of 1 tool failures", report["error"])
        self.assertEqual(len(report["executions"]), 1)

    def test_model_call_limit_prevents_endless_loops(self):
        endless = [plan(*[("list", "tasks.list")] * 10)] + [inputs()] * 50
        app = self.scripted(endless, engine_max_model_calls=4)
        report = app.engine.start("List forever")
        self.assertEqual(report["status"], "failed")
        self.assertIn("limit of 4 model calls", report["error"])
        self.assertEqual(len(self.model.prompts), 4)
        self.assertEqual(len(report["executions"]), 3)


class BlockedAndApprovalTests(EngineCase):
    def test_missing_information_blocks_then_resumes_with_the_answer(self):
        app = self.scripted([{"blocked": "Which business is this for?"}] + ONE_TASK)
        report = app.engine.start("Add a task for the business")
        self.assertEqual((report["status"], report["question"]), ("blocked", "Which business is this for?"))
        self.assertFalse(report["verified_complete"])
        self.assertIsNone(app.runs.get(report["run_id"])["finished_at"])
        with self.assertRaises(ValidationError):
            app.engine.resume(report["run_id"])                    # an answer is required
        done = app.engine.resume(report["run_id"], answer="Monsoor Motors")
        self.assertEqual((done["status"], done["verified_complete"]), ("completed", True))
        answers = json.loads(self.model.prompts[1][1].content)["answers_from_owner"]
        self.assertEqual(answers, [{"question": "Which business is this for?", "answer": "Monsoor Motors"}])
        shown_goal = json.loads(self.model.prompts[1][1].content)["goal"]
        self.assertIn('Q: "Which business is this for?" A: "Monsoor Motors"', shown_goal)
        self.assertEqual(app.runs.get(done["run_id"])["goal"], "Add a task for the business")   # stored goal unchanged

    def test_blocked_during_a_step(self):
        app = self.scripted([plan(("Create", "tasks.create")), {"blocked": "What should the task say?"},
                             inputs(title="Order parts"), SUMMARY])
        report = app.engine.start("Add a task")
        self.assertEqual((report["status"], self.statuses(report)), ("blocked", ["blocked"]))
        done = app.engine.resume(report["run_id"], answer="Order parts")
        self.assertTrue(done["verified_complete"])
        self.assertEqual(app.list("tasks")[0]["title"], "Order parts")

    def test_sensitive_step_pauses_for_approval_then_continues(self):
        app = self.scripted([plan(("Send it", "demo.send"), ("Log it", "tasks.create")), inputs(target="a"),
                             inputs(title="Sent"), SUMMARY])
        calls = self.add_tool("demo.send", ActionCategory.EXTERNAL_COMMUNICATION)
        report = app.engine.start("Send the message and log it")
        self.assertEqual((report["status"], self.statuses(report)), ("waiting_approval", ["blocked", "pending"]))
        self.assertEqual((calls, app.list("tasks")), ([], []))        # nothing ran
        approval = report["approval"]
        self.assertEqual((approval["status"], approval["category"], approval["requested_by"]),
                         ("pending", "external_communication", "jarvis-core"))

        still = app.engine.resume(report["run_id"])                    # resuming does not bypass approval
        self.assertEqual((still["status"], calls), ("waiting_approval", []))

        app.safety.approve(approval["id"])
        done = app.engine.resume(report["run_id"])
        self.assertEqual((done["status"], done["verified_complete"]), ("completed", True))
        self.assertEqual((calls, app.list("tasks")[0]["title"]), ([{"target": "a"}], "Sent"))

    def test_denied_approval_fails_the_run_without_acting(self):
        app = self.scripted([plan(("Pay", "demo.pay")), inputs(target="a")])
        calls = self.add_tool("demo.pay", ActionCategory.FINANCIAL)
        report = app.engine.start("Pay the invoice")
        app.safety.deny(report["approval"]["id"])
        done = app.engine.resume(report["run_id"])
        self.assertEqual((done["status"], calls), ("failed", []))
        self.assertIn("denied", done["error"])

    def test_engine_cannot_approve_its_own_request(self):
        app = self.scripted([plan(("Pay", "demo.pay")), inputs(target="a")])
        self.add_tool("demo.pay", ActionCategory.FINANCIAL)
        report = app.engine.start("Pay the invoice")
        with self.assertRaises(PermissionDenied):
            app.safety.approve(report["approval"]["id"], decided_by="jarvis-core")

    def test_cancel_and_resume_rules(self):
        app = self.scripted([{"blocked": "Which one?"}] + ONE_TASK)
        report = app.engine.start("Add a task")
        self.assertEqual(app.engine.cancel(report["run_id"])["status"], "cancelled")
        for action in (lambda: app.engine.resume(report["run_id"], answer="x"),
                       lambda: app.engine.cancel(report["run_id"])):
            with self.assertRaises(ValidationError):
                action()
        tool_run = app.tools.execute("tasks.list")["run_id"]
        with self.assertRaises(NotFoundError):
            app.engine.report(tool_run)


class RecoveryTests(EngineCase):
    def test_interrupted_run_resumes_without_repeating_finished_steps(self):
        def crash(messages):
            raise KeyboardInterrupt                                  # simulates JARVIS being killed mid-run

        app = self.scripted([plan(("First", "tasks.create"), ("Second", "tasks.create")),
                             inputs(title="First"), crash])
        with self.assertRaises(KeyboardInterrupt):
            app.engine.start("Add two tasks")
        run_id = app.runs.list()[0]["id"]
        self.assertEqual(app.runs.get(run_id)["status"], "running")

        restarted = self.make_app(provider=ScriptedProvider([inputs(title="Second"), SUMMARY]))
        restarted.announce_startup()
        self.assertEqual(restarted.engine.report(run_id)["status"], "interrupted")
        done = restarted.engine.resume(run_id)
        self.assertEqual((done["status"], done["verified_complete"]), ("completed", True))
        self.assertEqual(sorted(t["title"] for t in restarted.list("tasks")), ["First", "Second"])

    def test_step_that_succeeded_just_before_the_crash_is_not_run_twice(self):
        app = self.scripted(ONE_TASK[:2])
        report_id = None

        original = app.runs.update_plan_step

        def crash_after_success(plan_id, **fields):
            if fields.get("status") == "completed":
                raise KeyboardInterrupt
            return original(plan_id, **fields)

        app.runs.update_plan_step = crash_after_success
        with self.assertRaises(KeyboardInterrupt):
            app.engine.start("Add a task")
        report_id = app.runs.list()[0]["id"]
        self.assertEqual(app.runs.get(report_id)["plan"][0]["status"], "running")

        restarted = self.make_app(provider=ScriptedProvider([SUMMARY]))
        restarted.announce_startup()
        done = restarted.engine.resume(report_id)
        self.assertTrue(done["verified_complete"])
        self.assertEqual(len(restarted.list("tasks")), 1)


class MemoryAndContextTests(EngineCase):
    def test_relevant_memories_and_lessons_reach_the_model(self):
        app = self.scripted(ONE_TASK)
        memory = app.create("memories", {"content": "The supplier closes at 4pm", "confidence": 0.8})
        app.create("memories", {"content": "Unrelated note about parking"})
        lesson = app.create("experiences", {"title": "Supplier delay", "lesson": "Phone before noon"})
        report = app.engine.start("Add a task to call the supplier")
        self.assertEqual(report["context_used"], {"memories": [memory["id"]], "lessons": [lesson["id"]]})
        shown = json.loads(self.model.prompts[0][1].content)
        self.assertEqual(shown["known_memories"][0]["content"], "The supplier closes at 4pm")
        self.assertEqual(shown["known_memories"][0]["confidence"], 0.8)
        self.assertEqual(shown["lessons"][0]["lesson"], "Phone before noon")

    def test_outcomes_are_recorded_once_as_experiences(self):
        app = self.scripted(ONE_TASK + ONE_TASK)
        first = app.engine.start("Add a task to call the supplier")
        experiences = app.list("experiences")
        self.assertEqual(len(experiences), 1)
        self.assertEqual((experiences[0]["outcome"], experiences[0]["category"], experiences[0]["source"]),
                         ("success", "run", "jarvis-core"))
        self.assertIn(f"Run #{first['run_id']}", experiences[0]["description"])
        app.engine.start("Add a task to call the supplier")           # same goal again
        self.assertEqual(len(app.list("experiences")), 1)             # no duplicate
        self.assertTrue(first["verified_complete"])                    # bookkeeping is not a planned step
        self.assertEqual(len(first["executions"]), 1)

    def test_failures_are_recorded_and_unstarted_runs_are_not(self):
        app = self.scripted([plan(("Create", "tasks.create")), inputs(title="x", project_id=999),
                             inputs(title="x", project_id=999), "junk", "junk"])
        app.engine.start("Add a task")
        self.assertEqual([e["outcome"] for e in app.list("experiences")], ["failure"])
        app.engine.start("Something unplannable")
        self.assertEqual(len(app.list("experiences")), 1)

    def test_identical_memories_are_not_stored_twice(self):
        app = self.scripted([])
        first = app.tools.execute("memory.save", {"content": "Gate code  changes monthly"})["output"]
        again = app.tools.execute("memory.save", {"content": "gate code changes MONTHLY"})["output"]
        self.assertEqual((first["duplicate"], again["duplicate"], again["id"]), (False, True, first["id"]))
        other = app.tools.execute("memory.save", {"content": "Gate code changes monthly",
                                                  "project_id": app.list("projects")[0]["id"]})["output"]
        self.assertFalse(other["duplicate"])                            # a different project is a different fact
        self.assertEqual(len(app.list("memories")), 2)

    def test_execution_history_is_preserved(self):
        app = self.scripted(ONE_TASK)
        report = app.engine.start("Add a task")
        run = self.make_app().runs.get(report["run_id"])
        self.assertEqual([(s["tool"], s["status"], s["actor"]) for s in run["steps"]],
                         [("tasks.create", "succeeded", "jarvis-core"),
                          ("experience.record", "succeeded", "jarvis-core")])
        self.assertEqual(run["plan"][0]["inputs"], {"title": "Call the supplier"})
        actions = [e["action"] for e in app.events.list(category="engine")]
        self.assertEqual(actions, ["run.completed", "run.start"])


class UpgradeTests(JarvisTestCase):
    def test_version_2_runs_survive_the_upgrade(self):
        path = self.app.config.db_path
        path.unlink()
        for extra in ("-wal", "-shm"):
            path.with_name(path.name + extra).unlink(missing_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript(f"BEGIN;{MIGRATIONS[0]}{MIGRATIONS[1]}PRAGMA user_version = 2;COMMIT;")
        conn.execute("INSERT INTO runs (goal, status, created_at, updated_at) VALUES ('old run', 'completed', 'n', 'n')")
        conn.execute("INSERT INTO run_steps (run_id, position, tool, actor, status, started_at, finished_at) "
                     "VALUES (1, 1, 'tasks.list', 'user', 'succeeded', 'n', 'n')")
        conn.commit()
        conn.close()

        upgraded = self.make_app()
        self.assertEqual(upgraded.db.version(), SCHEMA_VERSION)
        self.assertTrue(upgraded.db.integrity_ok())
        old = upgraded.runs.get(1)
        self.assertEqual((old["goal"], old["status"], len(old["steps"]), old["plan"]), ("old run", "completed", 1, []))
        self.assertEqual([b["label"] for b in upgraded.backups.list()], ["pre-upgrade-v2"])
        self.assertTrue(upgraded.tools.execute("tasks.list")["ok"])
        with upgraded.db.connect() as conn:                              # foreign keys still intact
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            conn.execute("DELETE FROM runs WHERE id = 1")
        self.assertEqual(upgraded.runs.history(tool="tasks.list", limit=5)[-1]["run_id"] != 1, True)


class GoalApiTests(EngineCase):
    def serve(self):
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

    def test_submit_inspect_answer_and_cancel(self):
        self.scripted([{"blocked": "Which business?"}] + ONE_TASK + [{"blocked": "Again?"}])
        self.serve()
        status, report = self.call("POST", "/api/runs", {"goal": "Add a task"})
        self.assertEqual((status, report["status"]), (201, "blocked"))
        run_id = report["run_id"]
        self.assertEqual(self.call("POST", f"/api/runs/{run_id}/resume", {})[0], 400)
        status, done = self.call("POST", f"/api/runs/{run_id}/resume", {"answer": "Monsoor Motors"})
        self.assertEqual((status, done["verified_complete"]), (200, True))

        status, run = self.call("GET", f"/api/runs/{run_id}")
        self.assertEqual((status, run["report"]["status"], run["plan"][0]["tool"]), (200, "completed", "tasks.create"))
        self.assertEqual([r["id"] for r in self.call("GET", "/api/runs?kind=goal")[1]["items"]], [run_id])

        second = self.call("POST", "/api/runs", {"goal": "Another"})[1]
        self.assertEqual(self.call("POST", f"/api/runs/{second['run_id']}/cancel")[1]["status"], "cancelled")
        self.assertEqual(self.call("POST", f"/api/runs/{second['run_id']}/cancel")[0], 400)
        self.assertEqual(self.call("POST", "/api/runs", {"goal": ""})[0], 400)

    def test_no_model_is_reported_over_the_api(self):
        self.serve()
        status, body = self.call("POST", "/api/runs", {"goal": "Add a task"})
        self.assertEqual(status, 400)
        self.assertIn("No AI model is connected", body["error"])


if __name__ == "__main__":
    unittest.main()
