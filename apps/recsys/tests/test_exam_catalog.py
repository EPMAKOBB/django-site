from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from subjects.models import Subject
from apps.recsys.models import ExamVersion, TaskType, TaskTag, ExamScoreScale
from apps.recsys.service_utils.exam_catalog import get_exam_catalog, find_exam


class ExamCatalogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.subject = Subject.objects.create(name="Catalog subject")
        self.exam = ExamVersion.objects.create(subject=self.subject, name="Catalog exam", slug="catalog-exam")
        self.task_type = TaskType.objects.create(subject=self.subject, exam_version=self.exam, name="Catalog type", slug="catalog-type")

    def tearDown(self):
        cache.clear()

    def test_warm_catalog_only_checks_shared_generation(self):
        get_exam_catalog()
        with self.assertNumQueries(1):
            catalog = get_exam_catalog()
        self.assertEqual(find_exam(catalog, self.exam.slug)["subject"]["name"], self.subject.name)

    def test_save_and_slug_change_invalidate_warm_catalog(self):
        get_exam_catalog()
        self.exam.slug = "renamed-exam"
        self.exam.save()
        self.assertEqual(find_exam(get_exam_catalog(), "renamed-exam")["id"], self.exam.pk)

    def test_tag_relation_add_remove_and_reverse_clear_invalidate(self):
        tag = TaskTag.objects.create(subject=self.subject, name="Catalog tag")
        get_exam_catalog()
        self.task_type.required_tags.add(tag)
        self.assertEqual(get_exam_catalog()["types"][self.task_type.pk]["required_tags"][0]["id"], tag.pk)
        self.task_type.required_tags.remove(tag)
        self.assertEqual(get_exam_catalog()["types"][self.task_type.pk]["required_tags"], [])
        self.task_type.required_tags.add(tag)
        get_exam_catalog()
        tag.required_for_task_types.clear()
        self.assertEqual(get_exam_catalog()["types"][self.task_type.pk]["required_tags"], [])

    def test_scale_update_and_tag_delete_invalidate(self):
        tag = TaskTag.objects.create(subject=self.subject, name="Deleted tag")
        self.task_type.required_tags.add(tag)
        scale = ExamScoreScale.objects.create(exam_version=self.exam, max_primary=1, mapping=[0, 100])
        get_exam_catalog()
        scale.mapping = [0, 90]
        scale.save()
        self.assertEqual(get_exam_catalog()["scales"][self.exam.pk]["mapping"], [0, 90])
        tag.delete()
        self.assertEqual(get_exam_catalog()["types"][self.task_type.pk]["required_tags"], [])

    def test_first_html_contains_structure_for_guest_and_student(self):
        url = reverse("exam-page", args=[self.exam.slug])
        response = self.client.get(url)
        self.assertContains(response, "Catalog type")
        self.assertContains(response, "data-progress-demo")
        self.assertNotContains(response, 'class="exam-skeleton"')
        user = get_user_model().objects.create_user(username="catalog-student")
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertContains(response, "data-training-type-count")
        self.assertContains(response, f'data-type-count="{self.task_type.pk}" placeholder="—" disabled')
        self.assertContains(response, 'class="muted training-type-count__available"')
        self.assertNotContains(response, 'class="exam-type-card__score-value">0%')
