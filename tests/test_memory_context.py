import sqlite3
import unittest

from jarvis.db import MIGRATIONS, SCHEMA_VERSION
from jarvis.engine.context import ContextBuilder, fts_query
from jarvis.providers.scripted import ScriptedProvider
from support import JarvisTestCase

ANSWER = {"mode": "answer"}


class ContextBuilderTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.ctx = ContextBuilder(self.app)

    def remember(self, content, **meta):
        return self.app.create("memories", {"content": content, **meta})

    def fts_rows(self):
        return self.sql("SELECT kind, ref_id FROM knowledge_fts ORDER BY kind, ref_id")

    def test_finds_by_meaning_of_word_forms(self):
        memory = self.remember("I prefer short answers")
        self.assertEqual([m["id"] for m in self.ctx.search_memories("What are my preferences?")], [memory["id"]])
        self.assertEqual(self.ctx.search_memories("tyres"), [])

    def test_trusted_facts_rank_first(self):
        guess = self.remember("Sam works at the depot", verification_status="unverified", confidence=0.4)
        fact = self.remember("Sam works at the depot", verification_status="verified")
        self.assertEqual([m["id"] for m in self.ctx.search_memories("Where does Sam work?")], [fact["id"], guess["id"]])

    def test_archived_and_deleted_are_excluded_and_index_stays_in_sync(self):
        memory = self.remember("The gate code is 4512")
        self.assertEqual(self.fts_rows(), [("memory", memory["id"])])
        self.app.update("memories", memory["id"], {"content": "The side door code is 7781"})
        self.assertEqual(self.ctx.search_memories("gate"), [])
        self.assertEqual(len(self.ctx.search_memories("door code")), 1)
        self.assertEqual(self.fts_rows(), [("memory", memory["id"])])
        self.app.archive("memories", memory["id"])
        self.assertEqual(self.ctx.search_memories("door code"), [])
        self.app.restore("memories", memory["id"])
        self.assertEqual(len(self.ctx.search_memories("door code")), 1)
        self.approved_delete("memories", memory["id"])
        self.assertEqual(self.fts_rows(), [])

    def test_experiences_are_indexed_and_only_lessons_returned(self):
        lesson = self.app.create("experiences", {"title": "Supplier was late", "lesson": "Order two days early"})
        self.app.create("experiences", {"title": "Supplier visit", "description": "No lesson"})
        self.assertEqual([e["id"] for e in self.ctx.search_lessons("late supplier")], [lesson["id"]])
        self.app.archive("experiences", lesson["id"])
        self.assertEqual(self.ctx.search_lessons("supplier"), [])

    def test_personal_facts_always_included(self):
        prefers = self.remember("I prefer short answers", category="preference")
        self.remember("The office plant needs water on Fridays")
        built = self.ctx.build("What is the capital of France?")
        self.assertEqual([m["id"] for m in built["memories"]], [prefers["id"]])

    def test_build_respects_budget_and_project_scope(self):
        project = self.app.list("projects")[0]
        scoped = self.remember("Oil delivery arrives Tuesdays", project_id=project["id"])
        other = self.app.list("projects")[1]
        self.remember("Oil delivery arrives Mondays", project_id=other["id"])
        general = self.remember("Oil prices rose this year")
        ids = {m["id"] for m in self.ctx.build("oil delivery", project_id=project["id"])["memories"]}
        self.assertEqual(ids, {scoped["id"], general["id"]})
        long_one = self.remember("oil " * 300)
        built = self.ctx.build("oil", budget_chars=200)
        self.assertNotIn(long_one["id"], [m["id"] for m in built["memories"]])

    def test_queries_with_symbols_are_safe(self):
        self.remember('Code "A(1)" OR NOT x*')
        for text in ['"', "OR AND NOT", "a(b", "*", "", None, "   ", 'code "A(1)"']:
            with self.subTest(text=text):
                self.ctx.search_memories(text)
        self.assertIsNone(fts_query("the and of"))

    def test_memory_search_tool_uses_the_index(self):
        memory = self.remember("I prefer tea in the morning")
        found = self.app.tools.execute("memory.search", {"query": "preferences"})["output"]
        self.assertEqual([m["id"] for m in found], [memory["id"]])
        self.assertEqual(self.app.tools.execute("memory.search", {"query": "%"})["output"], [])


class ChatMemoryTests(JarvisTestCase):
    def scripted(self, replies):
        self.model = ScriptedProvider(replies)
        self.app = self.make_app(provider=self.model)
        return self.app

    def say(self, text, conversation=None):
        result = self.app.chat(text, conversation)
        return result["reply"], result["conversation"]["id"]

    def test_answers_are_given_what_jarvis_knows_and_cite_it(self):
        app = self.scripted([ANSWER, "Short version: 36.\n[memory: 1, 99]"])
        prefers = app.create("memories", {"content": "I prefer short answers", "category": "preference",
                                          "verification_status": "user_provided"})
        reply, _ = self.say("What's 15% of 240?")
        self.assertEqual(reply["content"], "Short version: 36.")          # marker removed
        self.assertEqual(reply["memory_refs"], [{"id": prefers["id"], "content": "I prefer short answers"}])
        prompt = self.model.prompts[1][0].content
        self.assertIn(f"[{prefers['id']}] I prefer short answers (user provided)", prompt)

    def test_no_marker_means_no_citation(self):
        self.scripted([ANSWER, "Hello."])
        self.app.create("memories", {"content": "I prefer short answers", "category": "preference"})
        reply, _ = self.say("Hello")
        self.assertIsNone(reply["memory_refs"])

    def test_explicit_remember_saves_as_owner_provided(self):
        self.scripted([{"mode": "remember", "fact": "I prefer short answers", "category": "preference"},
                       {"mode": "remember", "fact": "I prefer short answers.", "category": "preference"}])
        reply, conversation = self.say("Remember that I prefer short answers")
        self.assertEqual(reply["content"], "Noted. I'll remember “I prefer short answers”.")
        memory = self.app.list("memories")[0]
        self.assertEqual((memory["content"], memory["category"], memory["source"], memory["verification_status"]),
                         ("I prefer short answers", "preference", "user:chat", "user_provided"))
        again, _ = self.say("Remember I prefer short answers", conversation)
        self.assertIn("already had that", again["content"])
        self.assertEqual(len(self.app.list("memories")), 1)
        self.assertEqual(len(self.model.prompts), 2)                       # no engine run needed

    def test_model_cannot_save_without_the_owner_asking(self):
        # The real model chose "remember" for a passing remark, and even for a bare "Yes".
        self.scripted([{"mode": "remember", "fact": "I work late on Thursdays", "category": "personal"}, "Understood.",
                       {"mode": "remember", "fact": "I prefer short answers", "category": "preference"}, "Sure."])
        reply, conversation = self.say("I usually work late on Thursdays")
        self.assertTrue(reply["content"].endswith("Shall I remember that: “I work late on Thursdays”?"))
        self.assertEqual(self.app.list("memories"), [])
        self.say("No", conversation)                                     # declines the offer
        reply, _ = self.say("Hmm, okay then", conversation)               # model says "remember" again
        self.assertEqual(self.app.list("memories"), [])
        self.assertIn("Shall I remember", reply["content"])

    def test_offer_then_yes_saves(self):
        self.scripted([{"mode": "answer", "remember": "Call me Arfan", "category": "personal"},
                       "Pleased to meet you, Arfan."])
        reply, conversation = self.say("By the way, call me Arfan")
        # A plain statement gets a plain acknowledgement plus the offer.
        self.assertEqual(reply["content"], "Understood.\n\nShall I remember that: “Call me Arfan”?")
        self.assertEqual(self.app.list("memories"), [])                    # nothing saved yet
        self.assertIn("that question is asked separately", self.model.prompts[1][0].content)
        saved, _ = self.say("Yes please", conversation)
        self.assertEqual(saved["content"], "Noted. I'll remember “Call me Arfan”.")
        memory = self.app.list("memories")[0]
        self.assertEqual((memory["category"], memory["verification_status"]), ("personal", "user_provided"))
        self.assertEqual(len(self.model.prompts), 2)                       # "yes" needed no model call

    def test_offer_reply_cannot_claim_it_was_already_saved(self):
        # The real model said "I have noted that…" before anything was saved.
        self.scripted([{"mode": "answer", "remember": "I'm vegetarian", "category": "personal"},
                       "Noted. Your preference has been logged. Tofu works well in a stir-fry! I'll keep that in mind."])
        reply, _ = self.say("I'm vegetarian. What should I cook?")
        self.assertEqual(reply["content"], "Tofu works well in a stir-fry!\n\nShall I remember that: “I'm vegetarian”?")
        self.scripted([{"mode": "answer", "remember": "I'm vegetarian", "category": "personal"}, "I have noted that."])
        reply, _ = self.say("I'm vegetarian")
        self.assertTrue(reply["content"].startswith("Understood.\n\nShall I remember"))

    def test_offer_then_no_does_not_save(self):
        self.scripted([{"mode": "answer", "remember": "I'm vegetarian", "category": "personal"}, "Noted."])
        _, conversation = self.say("I'm vegetarian, for what it's worth")
        reply, _ = self.say("No thanks", conversation)
        self.assertEqual(reply["content"], "Understood. I won't keep that.")
        self.assertEqual(self.app.list("memories"), [])

    def test_offer_lapses_if_the_owner_moves_on(self):
        self.scripted([{"mode": "answer", "remember": "I work late on Thursdays", "category": "personal"}, "Got it.",
                       ANSWER, "Paris."])
        _, conversation = self.say("I work late on Thursdays")
        reply, _ = self.say("What's the capital of France?", conversation)
        self.assertEqual(reply["content"], "Paris.")
        self.assertEqual(self.app.list("memories"), [])

    def test_goals_get_ranked_context(self):
        self.scripted([{"mode": "act", "goal": "Add a task to call the supplier"},
                       {"plan": [{"description": "Create", "tool": "tasks.create"}]},
                       {"inputs": {"title": "Call supplier"}}, {"achieved": True, "summary": "Done."}])
        memory = self.app.create("memories", {"content": "The supplier closes at 4pm"})
        self.say("Remind me to call the supplier")
        import json
        shown = json.loads(self.model.prompts[1][1].content)
        self.assertEqual([m["id"] for m in shown["known_memories"]], [memory["id"]])


class UpgradeTests(JarvisTestCase):
    def test_version_4_database_is_indexed_on_upgrade(self):
        path = self.app.config.db_path
        path.unlink()
        for extra in ("-wal", "-shm"):
            path.with_name(path.name + extra).unlink(missing_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript("BEGIN;" + "".join(MIGRATIONS[:4]) + "PRAGMA user_version = 4;COMMIT;")
        conn.execute("INSERT INTO memories (content, created_at, updated_at) VALUES ('Old fact about parking', 'n', 'n')")
        conn.execute("INSERT INTO experiences (title, lesson, created_at, updated_at) "
                     "VALUES ('Old trip', 'Pack light', 'n', 'n')")
        conn.commit()
        conn.close()
        upgraded = self.make_app()
        self.assertEqual(upgraded.db.version(), SCHEMA_VERSION)
        ctx = ContextBuilder(upgraded)
        self.assertEqual([m["content"] for m in ctx.search_memories("parking")], ["Old fact about parking"])
        self.assertEqual([e["lesson"] for e in ctx.search_lessons("trip")], ["Pack light"])
        self.assertIn("pre-upgrade-v4", [b["label"] for b in upgraded.backups.list()])
        self.assertTrue(upgraded.db.integrity_ok())


if __name__ == "__main__":
    unittest.main()
