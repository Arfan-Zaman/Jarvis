import unittest

from jarvis.common import NotFoundError, ValidationError
from support import JarvisTestCase


class TaskTests(JarvisTestCase):
    def test_create(self):
        task = self.app.create("tasks", {"title": "Order brake pads", "priority": "high", "due_at": "2026-12-01"})
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["due_at"], "2026-12-01")
        self.assertIsNone(task["completed_at"])
        self.assertEqual(self.app.tasks.open_count(), 1)

    def test_complete_and_reopen(self):
        task = self.app.create("tasks", {"title": "Do it"})
        done = self.app.complete_task(task["id"])
        self.assertEqual(done["task"]["status"], "completed")
        self.assertTrue(done["task"]["completed_at"])
        self.assertIsNone(done["experience"])
        self.assertEqual(self.app.tasks.open_count(), 0)
        self.assertEqual(self.app.counts()["tasks_completed"], 1)

        reopened = self.app.reopen_task(task["id"])
        self.assertEqual(reopened["status"], "pending")
        self.assertIsNone(reopened["completed_at"])

    def test_completing_twice_keeps_the_original_completion_time(self):
        task = self.app.create("tasks", {"title": "Do it"})
        first = self.app.complete_task(task["id"])["task"]["completed_at"]
        second = self.app.complete_task(task["id"])["task"]["completed_at"]
        self.assertEqual(first, second)

    def test_completing_with_a_lesson_records_an_experience(self):
        project = self.app.projects.get_by_name("Aureus Detailing")
        task = self.app.create("tasks", {"title": "Trial run", "project_id": project["id"]})
        result = self.app.complete_task(task["id"], lesson="Book the bay a day ahead")
        experience = result["experience"]
        self.assertEqual(experience["lesson"], "Book the bay a day ahead")
        self.assertEqual(experience["task_id"], task["id"])
        self.assertEqual(experience["project_id"], project["id"])
        self.assertEqual(experience["source"], f"task:{task['id']}")

    def test_validation(self):
        for bad in ({"title": ""}, {"title": "x", "status": "someday"}, {"title": "x", "priority": "asap"},
                    {"title": "x", "due_at": "next week"}, {"title": "x", "project_id": 9999}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.app.create("tasks", bad)
        with self.assertRaises(NotFoundError):
            self.app.complete_task(4242)

    def test_urgent_open_tasks_sort_first(self):
        self.app.create("tasks", {"title": "low", "priority": "low"})
        self.app.create("tasks", {"title": "urgent", "priority": "urgent"})
        done = self.app.create("tasks", {"title": "done", "priority": "urgent"})
        self.app.complete_task(done["id"])
        self.assertEqual([t["title"] for t in self.app.list("tasks")], ["urgent", "low", "done"])


class ProjectTests(JarvisTestCase):
    def test_create(self):
        project = self.app.create("projects", {"name": "Home Lab", "description": "Tinkering."})
        self.assertEqual(project["slug"], "home-lab")
        self.assertEqual(project["status"], "active")
        self.assertEqual(self.app.get("projects", project["id"])["name"], "Home Lab")
        self.assertEqual(self.app.counts()["projects"], 3)

    def test_names_are_unique(self):
        with self.assertRaises(ValidationError):
            self.app.create("projects", {"name": "Monsoor Motors"})

    def test_rename_updates_slug(self):
        project = self.app.create("projects", {"name": "Old Name"})
        renamed = self.app.update("projects", project["id"], {"name": "New Name"})
        self.assertEqual(renamed["slug"], "new-name")

    def test_validation(self):
        for bad in ({"name": ""}, {"name": "!!!"}, {"name": "x", "status": "dead"}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.app.create("projects", bad)

    def test_archive_and_restore(self):
        project = self.app.create("projects", {"name": "Paused Idea"})
        self.app.archive("projects", project["id"])
        self.assertNotIn("Paused Idea", [p["name"] for p in self.app.list("projects")])
        self.app.restore("projects", project["id"])
        self.assertIn("Paused Idea", [p["name"] for p in self.app.list("projects")])


class ExperienceTests(JarvisTestCase):
    def test_store_and_retrieve(self):
        stored = self.app.create("experiences", {
            "title": "Tried the new supplier", "description": "Parts arrived late.",
            "outcome": "failure", "lesson": "Confirm delivery dates in writing",
            "category": "suppliers", "source": "user", "confidence": 0.9,
            "verification_status": "user_provided"})
        fetched = self.app.get("experiences", stored["id"])
        self.assertEqual(fetched["outcome"], "failure")
        self.assertEqual(fetched["lesson"], "Confirm delivery dates in writing")
        self.assertEqual(fetched["confidence"], 0.9)
        self.assertTrue(fetched["created_at"])

    def test_lessons_lookup(self):
        self.app.create("experiences", {"title": "Supplier delay", "lesson": "Confirm dates"})
        self.app.create("experiences", {"title": "No lesson here"})
        archived = self.app.create("experiences", {"title": "Supplier old", "lesson": "Outdated"})
        self.app.archive("experiences", archived["id"])
        self.assertEqual([e["lesson"] for e in self.app.experiences.lessons()], ["Confirm dates"])
        self.assertEqual([e["lesson"] for e in self.app.experiences.lessons("supplier")], ["Confirm dates"])
        self.assertEqual(self.app.experiences.lessons("unrelated"), [])

    def test_validation(self):
        for bad in ({"title": ""}, {"title": "x", "outcome": "great"}, {"title": "x", "task_id": 777}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.app.create("experiences", bad)

    def test_delete_requires_approval(self):
        stored = self.app.create("experiences", {"title": "x"})
        self.assertEqual(self.app.delete("experiences", stored["id"])["status"], "approval_required")
        self.assertEqual(self.approved_delete("experiences", stored["id"])["status"], "deleted")


if __name__ == "__main__":
    unittest.main()
