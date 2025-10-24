import json
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.recsys.models import (
    Subject,
    ExamVersion,
    Skill,
    TaskType,
    Task,
    TaskSkill,
    TaskTag,
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
        )
        TaskSkill.objects.create(task=self.task, skill=self.skill, weight=1.0)
        self.tag = TaskTag.objects.create(subject=self.subject, name="делители", slug="deliteli")
        self.task.tags.add(self.tag)
        self.ttype.required_tags.add(self.tag)

    def test_endpoints(self):
        # next task
        resp = self.client.get("/api/next-task/", {"user": self.user.id})
        self.assertEqual(resp.status_code, 200)
        task_payload = resp.json()
        self.assertEqual(task_payload["id"], self.task.id)
        self.assertEqual(task_payload["difficulty_level"], 0)
        self.assertEqual(task_payload["correct_answer"], {})
        self.assertIsNone(task_payload["image"])
        self.assertEqual([tag["name"] for tag in task_payload["tags"]], ["делители"])
        self.assertEqual(
            [tag["name"] for tag in task_payload["type"]["required_tags"]],
            ["делители"],
        )
        # attempt
        payload = {"user": self.user.id, "task": self.task.id, "is_correct": True}
        resp = self.client.post("/api/attempts/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        TypeMastery.objects.update_or_create(user=self.user, task_type=self.ttype, defaults={"mastery": 0.8})
        # progress
        resp = self.client.get("/api/progress/", {"user": self.user.id})
        self.assertEqual(resp.status_code, 200)
        progress_payload = resp.json()
        data = progress_payload["skill_masteries"]
        self.assertGreater(data[0]["mastery"], 0)
        type_masteries = progress_payload["type_masteries"]
        self.assertEqual(len(type_masteries), 1)
        type_entry = type_masteries[0]
        self.assertAlmostEqual(type_entry["mastery"], 0.8)
        self.assertAlmostEqual(type_entry["effective_mastery"], 0.8)
        self.assertEqual(type_entry["required_count"], 1)
        self.assertEqual(type_entry["covered_count"], 1)
        self.assertEqual([tag["name"] for tag in type_entry["required_tags"]], ["делители"])
        self.assertEqual(set(type_entry["covered_tag_ids"]), {self.tag.id})
        self.assertEqual(self.task.subject, self.subject)
        self.assertEqual(self.task.exam_version, self.exam_version)
