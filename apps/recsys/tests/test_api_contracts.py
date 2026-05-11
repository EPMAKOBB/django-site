import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import (
    ExamVersion,
    Skill,
    Subject,
    Task,
    TaskSkill,
    TaskTag,
    TaskType,
    TypeMastery,
)


class ApiContractsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="user")
        self.client.force_login(self.user)
        self.subject = Subject.objects.create(name="Subject")
        self.exam_version = ExamVersion.objects.create(name="V1", subject=self.subject)
        self.skill = Skill.objects.create(name="Skill", subject=self.subject)
        self.ttype = TaskType.objects.create(name="Type", subject=self.subject)
        self.task = Task.objects.create(
            type=self.ttype,
            title="Task",
            subject=self.subject,
            exam_version=self.exam_version,
            status=Task.Status.PUBLISHED,
        )
        TaskSkill.objects.create(task=self.task, skill=self.skill, weight=1.0)
        self.tag = TaskTag.objects.create(
            subject=self.subject,
            name="Tag",
            slug="tag",
        )
        self.task.tags.add(self.tag)
        self.ttype.required_tags.add(self.tag)

    def test_endpoints(self):
        resp = self.client.get("/api/next-task/", {"user": self.user.id})
        self.assertEqual(resp.status_code, 200)
        next_payload = resp.json()
        task_payload = next_payload["task"]
        self.assertEqual(task_payload["id"], self.task.id)
        self.assertEqual(task_payload["difficulty_level"], 0)
        self.assertEqual(task_payload["correct_answer"], {})
        self.assertIsNone(task_payload["image"])
        self.assertEqual([tag["name"] for tag in task_payload["tags"]], ["Tag"])
        self.assertEqual(
            [tag["name"] for tag in task_payload["type"]["required_tags"]],
            ["Tag"],
        )
        self.assertIn("score_snapshot", next_payload)
        self.assertIn("reason_snapshot", next_payload)
        self.assertIn("weak_tags_snapshot", next_payload)

        resp = self.client.get("/api/recommendations/", {"limit": 3})
        self.assertEqual(resp.status_code, 200)
        recommendations_payload = resp.json()
        self.assertEqual(len(recommendations_payload), 1)
        self.assertEqual(recommendations_payload[0]["task"]["id"], self.task.id)
        self.assertIn("score_snapshot", recommendations_payload[0])
        self.assertIn("reason_snapshot", recommendations_payload[0])
        self.assertIn("weak_tags_snapshot", recommendations_payload[0])
        recommendation_id = next_payload["recommendation_id"]
        self.assertIsNotNone(recommendation_id)

        payload = {"user": self.user.id, "task": self.task.id, "is_correct": True}
        resp = self.client.post(
            "/api/attempts/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        TypeMastery.objects.update_or_create(
            user=self.user,
            task_type=self.ttype,
            defaults={"mastery": 0.8},
        )

        resp = self.client.get("/api/progress/", {"user": self.user.id})
        self.assertEqual(resp.status_code, 200)
        progress_payload = resp.json()
        data = progress_payload["skill_masteries"]
        self.assertGreater(data[0]["mastery"], 0)
        type_masteries = progress_payload["type_masteries"]
        self.assertEqual(len(type_masteries), 1)
        type_entry = type_masteries[0]
        self.assertAlmostEqual(type_entry["mastery"], 0.8)
        self.assertAlmostEqual(type_entry["effective_mastery"], 1.0)
        self.assertEqual(len(type_entry["tag_progress"]), 1)
        tag_entry = type_entry["tag_progress"][0]
        self.assertEqual(tag_entry["tag_id"], self.tag.id)
        self.assertEqual(tag_entry["tag_name"], self.tag.name)
        self.assertEqual(tag_entry["total_count"], 1)
        self.assertEqual(tag_entry["solved_count"], 1)
        self.assertAlmostEqual(tag_entry["ratio"], 1.0)
        self.assertAlmostEqual(tag_entry["coverage_ratio"], 1.0)
        self.assertEqual(type_entry["required_count"], 1)
        self.assertEqual(type_entry["covered_count"], 1)
        self.assertEqual([tag["name"] for tag in type_entry["required_tags"]], ["Tag"])
        self.assertEqual(set(type_entry["covered_tag_ids"]), {self.tag.id})
        self.assertEqual(self.task.subject, self.subject)
        self.assertEqual(self.task.exam_version, self.exam_version)

        resp = self.client.get("/api/recommendation-history/", {"limit": 5})
        self.assertEqual(resp.status_code, 200)
        history_payload = resp.json()
        self.assertEqual(len(history_payload), 1)
        history_entry = history_payload[0]
        self.assertEqual(history_entry["id"], recommendation_id)
        self.assertEqual(history_entry["task"]["id"], self.task.id)
        self.assertEqual(history_entry["status"], "completed")
        self.assertTrue(history_entry["completed"])
        self.assertIsNotNone(history_entry["attempt"])
        self.assertIn("score_snapshot", history_entry)
        self.assertIn("reason_snapshot", history_entry)
        self.assertIn("weak_tags_snapshot", history_entry)

        resp = self.client.get(
            "/api/recommendation-history/",
            {"status": "completed", "source_mode": "training", "limit": 5},
        )
        self.assertEqual(resp.status_code, 200)
        filtered_history = resp.json()
        self.assertEqual(len(filtered_history), 1)
        self.assertEqual(filtered_history[0]["id"], recommendation_id)
