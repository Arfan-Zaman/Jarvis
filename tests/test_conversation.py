import json
import sqlite3
import unittest

from jarvis.db import MIGRATIONS, SCHEMA_VERSION
from jarvis.engine.conversation import system_prompt
from jarvis.providers.scripted import ScriptedProvider
from jarvis.safety import ActionCategory
from jarvis.tools import Tool
from support import JarvisTestCase

ANSWER = {"mode": "answer"}
ACHIEVED = {"achieved": True, "summary": "Done."}


def act(goal):
    return {"mode": "act", "goal": goal}


def plan(*steps):
    return {"plan": [{"description": d, "tool": t} for d, t in steps]}


def inputs(**values):
    return {"inputs": values}


class ConversationCase(JarvisTestCase):
    def scripted(self, replies):
        self.model = ScriptedProvider(replies)
        self.app = self.make_app(provider=self.model)
        return self.app

    def say(self, text, conversation_id=None):
        result = self.app.chat(text, conversation_id)
        return result["reply"], result["conversation"]["id"]


class AnswerTests(ConversationCase):
    def test_plain_conversation_just_answers(self):
        self.scripted([ANSWER, "Good evening. How can I help?"])
        reply, _ = self.say("Good evening, JARVIS. Got a minute to chat?")
        self.assertEqual((reply["role"], reply["content"], reply["run_id"]),
                         ("assistant", "Good evening. How can I help?", None))
        self.assertEqual(self.app.runs.list(), [])
        self.assertTrue(self.model.json_requests >= 1)            # routing asked for JSON

    def test_unusable_routing_falls_back_to_answering(self):
        self.scripted(["not json at all", "15% of 240 is 36."])
        reply, _ = self.say("What's 15% of 240?")
        self.assertEqual(reply["content"], "15% of 240 is 36.")
        self.assertEqual(self.app.runs.list(), [])

    def test_act_without_a_goal_is_treated_as_answer(self):
        self.scripted([{"mode": "act", "goal": "  "}, "Could you say a little more?"])
        self.assertEqual(self.say("Do the thing")[0]["content"], "Could you say a little more?")

    def test_self_description_comes_from_the_live_tools(self):
        self.scripted([ANSWER, "I can manage tasks and memories."])
        self.say("What can you do?")
        prompt = self.model.prompts[1][0].content
        for tool in self.app.tools.list():
            self.assertIn(tool["description"], prompt)
        self.assertIn("Never say you have done", prompt)
        self.assertIn("Reason first; resolve always", prompt)
        self.assertIn("Do not simply agree", prompt)
        self.assertNotIn("browse the web", prompt)                     # it can, since Phase 3.4
        self.assertIn("search the web", prompt)
        self.assertEqual(system_prompt(self.app.tools.list()), prompt)

    def test_history_is_carried_forward(self):
        self.scripted([ANSWER, "Nice to meet you, Arfan.", ANSWER, "You said your name is Arfan."])
        _, conversation = self.say("My name is Arfan")
        self.say("What's my name?", conversation)
        sent = [m.content for m in self.model.prompts[3]]
        self.assertIn("My name is Arfan", sent)
        self.assertIn("Nice to meet you, Arfan.", sent)


class ActTests(ConversationCase):
    def test_request_is_carried_out_and_reported_from_the_record(self):
        self.scripted([act("Add a task to call Sam tomorrow"), plan(("Create the task", "tasks.create")),
                       inputs(title="Call Sam"), ACHIEVED])
        reply, _ = self.say("Add a task to call Sam tomorrow")
        self.assertEqual(reply["content"], "Completed. I added the task “Call Sam”.")
        self.assertTrue(reply["run_id"])
        run = self.app.runs.get(reply["run_id"])
        self.assertEqual((run["goal"], run["status"]), ("Add a task to call Sam tomorrow", "completed"))
        self.assertEqual(self.app.list("tasks")[0]["title"], "Call Sam")
        self.assertEqual(len(self.model.prompts), 4)               # no extra call to phrase the reply

    def test_several_changes_are_all_reported(self):
        self.scripted([act("Add a task and remember the code"),
                       plan(("Task", "tasks.create"), ("Note", "memory.save")),
                       inputs(title="Order oil"), inputs(content="The gate code is on the fridge"), ACHIEVED])
        reply, _ = self.say("Add a task to order oil and remember the gate code is on the fridge")
        self.assertEqual(reply["content"],
                         "Completed. I added the task “Order oil” and noted “The gate code is on the fridge”.")

    def test_refining_a_new_task_is_reported_as_one_change(self):
        self.scripted([act("Add a task to call Sam tomorrow"),
                       plan(("Create", "tasks.create"), ("Set due date", "tasks.update"), ("Note", "memory.save")),
                       inputs(title="Call Sam"), inputs(id=1, due_at="2030-01-02"), inputs(content="Sam likes calls."),
                       ACHIEVED])
        reply, _ = self.say("Add a task to call Sam tomorrow")
        self.assertEqual(reply["content"], "Completed. I added the task “Call Sam” and noted “Sam likes calls”.")

    def test_the_model_is_told_the_date_and_project_names(self):
        self.scripted([act("List my tasks"), plan(("List", "tasks.list")), inputs(), ACHIEVED, "None yet."])
        self.say("What are my tasks?")
        plan_request = json.loads(self.model.prompts[1][1].content)
        self.assertRegex(plan_request["today"], r"^[A-Z][a-z]+day \d{2} [A-Z][a-z]+ \d{4}, \d{2}:\d{2}$")
        self.assertIn("Never pick a project yourself", self.model.prompts[1][0].content)
        narration = self.model.prompts[-1][0].content
        self.assertIn("1 = Monsoor Motors", narration)
        self.assertIn("It is now", narration)

    def test_model_cannot_add_claims_beyond_the_record(self):
        self.scripted([act("Add a task to call Sam"), plan(("Create", "tasks.create")), inputs(title="Call Sam"),
                       {"achieved": True, "summary": "I also emailed Sam and booked a meeting."}])
        reply, _ = self.say("Add a task to call Sam")
        self.assertNotIn("email", reply["content"].lower())
        self.assertNotIn("meeting", reply["content"].lower())

    def test_lookups_are_answered_from_returned_data_only(self):
        self.scripted([act("List my open tasks"), plan(("List", "tasks.list")), inputs(), ACHIEVED,
                       "You have one open task: Call Sam."])
        self.app.create("tasks", {"title": "Call Sam"})
        reply, _ = self.say("What's on my list?")
        self.assertEqual(reply["content"], "You have one open task: Call Sam.")
        narration = self.model.prompts[-1]
        self.assertIn("Call Sam", narration[0].content)              # the real data was supplied
        self.assertIn("ONLY the results", narration[0].content)
        self.assertEqual(narration[1].content, "What's on my list?")
        self.assertEqual(self.app.list("tasks")[0]["title"], "Call Sam")   # nothing changed

    def test_failure_is_reported_honestly(self):
        self.scripted([act("Add a task to project 999"), plan(("Create", "tasks.create")),
                       inputs(title="x", project_id=999), inputs(title="x", project_id=998)])
        reply, _ = self.say("Add a task to project 999")
        self.assertTrue(reply["content"].startswith("The operation failed."))
        self.assertIn("Nothing was changed, and I have not marked it as complete.", reply["content"])
        self.assertNotIn("Completed", reply["content"])
        self.assertEqual(self.app.runs.get(reply["run_id"])["status"], "failed")

    def test_engine_refusing_to_start_becomes_a_notice(self):
        self.scripted([act("Add a task"), plan(("x", "nope.tool")), plan(("x", "nope.tool"))])
        reply, _ = self.say("Add a task")
        self.assertIn("The operation failed", reply["content"])


class FollowUpTests(ConversationCase):
    def test_question_is_asked_and_the_next_message_answers_it(self):
        self.scripted([act("Add a task for the business to follow up the customer"),
                       {"blocked": "Which business: Monsoor Motors or Aureus Detailing?"},
                       plan(("Create", "tasks.create")), inputs(title="Follow up the customer", project_id=2),
                       ACHIEVED])
        reply, conversation = self.say("Add a task for the business to follow up the customer")
        self.assertEqual(reply["content"], "One decision is needed before I proceed: Which business: Monsoor Motors or Aureus Detailing?")
        self.assertEqual(self.app.runs.get(reply["run_id"])["status"], "blocked")

        prompts_before = len(self.model.prompts)
        answer, _ = self.say("Aureus Detailing", conversation)
        self.assertEqual(answer["content"], "Completed. I added the task “Follow up the customer”.")
        self.assertEqual(answer["run_id"], reply["run_id"])           # same action, continued
        # The answer went straight to the paused action: no new routing call.
        self.assertEqual(json.loads(self.model.prompts[prompts_before][1].content)["request"], "PLAN")
        context = self.app.runs.get(reply["run_id"])["context"]
        self.assertEqual(context["answers"][0]["answer"], "Aureus Detailing")

    def test_pending_question_can_be_cancelled(self):
        self.scripted([act("Add a task for the customer"), {"blocked": "Which customer?"}])
        reply, conversation = self.say("Add a task for the customer")
        dropped, _ = self.say("Never mind", conversation)
        self.assertIn("dropped", dropped["content"])
        self.assertEqual(self.app.runs.get(reply["run_id"])["status"], "cancelled")

    def test_after_an_answered_question_routing_resumes_normally(self):
        self.scripted([act("Add a task"), {"blocked": "What should it say?"},
                       plan(("Create", "tasks.create")), inputs(title="Buy filters"), ACHIEVED,
                       "You're welcome."])                # "Thanks" is small talk: no routing step
        _, conversation = self.say("Add a task")
        self.say("Buy filters", conversation)
        reply, _ = self.say("Thanks", conversation)
        self.assertEqual((reply["content"], reply["run_id"]), ("You're welcome.", None))

    def test_approval_is_explained_and_never_granted_by_chat(self):
        app = self.scripted([act("Send the supplier a message"), plan(("Send", "demo.send")),
                             inputs(target="supplier"), ANSWER, "It is waiting for you."])
        calls = []
        app.tools.register(Tool("demo.send", "Send a message (test only).", ActionCategory.EXTERNAL_COMMUNICATION,
                                lambda a, v, actor: calls.append(v) or {"sent": True},
                                {"target": {"type": "string"}}))
        reply, conversation = self.say("Send the supplier a message")
        self.assertIn("needs your approval", reply["content"])
        self.assertIn("System page", reply["content"])
        run = self.app.runs.get(reply["run_id"])
        self.assertEqual(run["status"], "waiting_approval")
        # Saying "yes, approve it" in chat does not approve or run anything.
        self.say("Yes, approve it", conversation)
        self.assertEqual(calls, [])
        self.assertEqual(self.app.safety.list_approvals("pending")[0]["requested_by"], "jarvis-core")


class StorageTests(ConversationCase):
    def test_messages_record_their_action(self):
        self.scripted([act("Add a task"), plan(("Create", "tasks.create")), inputs(title="X"), ACHIEVED])
        reply, conversation = self.say("Add a task called X")
        stored = self.app.get("conversations", conversation)["messages"]
        self.assertEqual([m["run_id"] for m in stored], [None, reply["run_id"]])

    def test_version_3_database_gains_message_links(self):
        path = self.app.config.db_path
        path.unlink()
        for extra in ("-wal", "-shm"):
            path.with_name(path.name + extra).unlink(missing_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript("BEGIN;" + "".join(MIGRATIONS[:3]) + "PRAGMA user_version = 3;COMMIT;")
        conn.execute("INSERT INTO conversations (title, created_at, updated_at) VALUES ('old', 'n', 'n')")
        conn.execute("INSERT INTO messages (conversation_id, role, content, created_at) VALUES (1, 'user', 'hi', 'n')")
        conn.commit()
        conn.close()
        upgraded = self.make_app()
        self.assertEqual(upgraded.db.version(), SCHEMA_VERSION)
        message = upgraded.get("conversations", 1)["messages"][0]
        self.assertEqual((message["content"], message["run_id"]), ("hi", None))
        self.assertEqual([b["label"] for b in upgraded.backups.list()], ["pre-upgrade-v3"])


if __name__ == "__main__":
    unittest.main()
