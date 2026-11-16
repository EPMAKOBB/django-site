import io
import tempfile
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.recsys.models import (Subject, ExamVersion, AnswerSchema, TaskType, Task,
    VariantTemplate, VariantTask, VariantAssignment, VariantAttempt, Attempt,
    WrittenSolution, SolutionAssessment)
from apps.recsys.service_utils import variants
from apps.recsys.service_utils.exam_context import public_snapshot
from apps.recsys.service_utils.rebuild_learning import rebuild_learning_state
from apps.recsys.solution_views import token_for


def jpeg():
    output = io.BytesIO()
    Image.new('RGB', (160, 220), 'white').save(output, 'JPEG')
    return SimpleUploadedFile('page.jpg', output.getvalue(), content_type='image/jpeg')


class WrittenSolutionTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = get_user_model().objects.create_user(username='writer')
        self.other = get_user_model().objects.create_user(username='other')
        self.client.force_login(self.user)
        subject = Subject.objects.create(name='Mathematics')
        self.exam = ExamVersion.objects.create(subject=subject, name='EGE 2027', exam_kind='ege', year=2027)
        schema = AnswerSchema.objects.create(name='Written', config={
            'rows': 1, 'cols': 1, 'input_type': 'text', 'ui_hint': 'textarea', 'manual_check': True})
        task_type = TaskType.objects.create(subject=subject, exam_version=self.exam, name='13',
            display_order=13, answer_schema=schema, scoring_scheme='manual_scaled', max_score=2)
        self.task = Task.objects.create(subject=subject, exam_version=self.exam, type=task_type,
            title='Prove and calculate', description='Find the roots.', correct_answer='Final answer',
            reference_solution='Reference reasoning', assessment_criteria='2: both parts justified.\n1: first part justified.',
            status='published')
        template = VariantTemplate.objects.create(name='Written work', exam_version=self.exam)
        self.row = VariantTask.objects.create(template=template, task=self.task, order=1)
        assignment = VariantAssignment.objects.create(template=template, user=self.user)
        self.work = variants.start_new_attempt(self.user, assignment.pk)
        self.work.mode = VariantAttempt.Mode.TRAINING
        self.work.save(update_fields=['mode'])
        self.url = reverse('written-solution', args=[self.work.pk, self.row.pk])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.solution = WrittenSolution.objects.get()

    def post(self, action, **data):
        return self.client.post(self.url, {'action': action, **data})

    def submit(self):
        self.assertEqual(self.post('upload', photos=jpeg()).status_code, 302)
        self.assertEqual(self.post('submit', text='See attached proof').status_code, 302)
        self.solution.refresh_from_db()

    def test_training_photo_reveal_and_self_assessment_end_to_end(self):
        self.submit()
        self.assertIsNotNone(self.solution.submitted_at)
        self.assertIsNone(self.solution.task_attempt.score)
        self.assertTrue(variants.calculate_attempt_primary_summary(self.work)['is_provisional'])
        self.assertEqual(self.post('reveal').status_code, 302)
        self.assertEqual(self.post('assess', score='1', comment='Only first part justified').status_code, 302)
        grade = SolutionAssessment.objects.get()
        self.assertEqual((grade.source, grade.author_id, grade.score), ('self', self.user.pk, 1))
        self.solution.task_attempt.refresh_from_db()
        self.assertEqual(self.solution.task_attempt.score, 1)
        self.assertFalse(self.solution.task_attempt.is_valid_attempt)
        summary = variants.calculate_attempt_primary_summary(self.work)
        self.assertEqual(summary['primary_total'], 1)
        self.assertFalse(summary['is_provisional'])
        self.assertEqual(summary['self_assessed_count'], 1)
        self.assertEqual(self.client.get(reverse('written-solution-list', args=[self.work.pk])).status_code, 200)

    def test_oge_uses_the_same_submission_workflow(self):
        self.exam.exam_kind = 'oge'
        self.exam.save(update_fields=['exam_kind'])
        self.submit()
        self.assertEqual(self.post('reveal').status_code, 302)
        self.assertEqual(self.post('assess', score='2').status_code, 302)
        self.assertEqual(SolutionAssessment.objects.get().score, 2)

    def test_exam_cannot_reveal_until_whole_work_is_completed(self):
        self.work.mode = 'exam'
        self.work.save(update_fields=['mode'])
        self.submit()
        self.assertContains(self.post('reveal'), 'после завершения всей работы')
        self.solution.refresh_from_db()
        self.assertIsNone(self.solution.revealed_at)
        variants.finalize_attempt(self.user, self.work.pk)
        self.assertEqual(self.post('reveal').status_code, 302)
        self.assertEqual(self.post('assess', score='2').status_code, 302)
        response = self.client.get(f'/api/variants/attempts/{self.work.pk}/').json()
        self.assertEqual(response['primary_summary']['primary_total'], 2)
        self.assertEqual(response['tasks_progress'][0]['assessment_source'], 'self')

    def test_reference_is_frozen_and_not_leaked_by_work_api(self):
        payload = self.client.get(f'/api/variants/attempts/{self.work.pk}/').json()
        self.assertNotIn('Reference reasoning', str(payload))
        self.assertNotIn('both parts justified', str(payload))
        self.assertNotContains(self.client.get(self.url), 'Reference reasoning')
        Task.objects.filter(pk=self.task.pk).update(reference_solution='Edited reference')
        self.submit()
        self.post('reveal')
        response = self.client.get(self.url)
        self.assertContains(response, 'Reference reasoning')
        self.assertNotContains(response, 'Edited reference')
        self.assertNotIn('reference_solution', public_snapshot({'reference_solution': 'hidden'}, reveal=True))

    def test_foreign_user_cannot_access_solution_or_photo(self):
        self.post('upload', photos=jpeg())
        photo = self.solution.photos.get()
        self.client.force_login(self.other)
        for url in [self.url, reverse('solution-photo', args=[photo.pk]),
                    reverse('solution-status', args=[self.solution.pk]),
                    reverse('solution-qr', args=[self.solution.pk])]:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('solution-photo', args=[photo.pk])).status_code, 302)

    def test_photos_cannot_be_fetched_through_public_media(self):
        self.post('upload', photos=jpeg())
        photo = self.solution.photos.get()
        self.assertEqual(self.client.get('/media/_private_solutions/' + photo.image.name).status_code, 404)
        self.assertEqual(self.client.get(reverse('solution-photo', args=[photo.pk])).status_code, 200)

    def test_phone_token_upload_without_account_and_revoke(self):
        phone = Client()
        url = reverse('solution-phone', args=[token_for(self.solution)])
        response = phone.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'mc.yandex')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')
        self.assertEqual(phone.post(url, {'photos': jpeg()}).status_code, 302)
        self.assertEqual(self.solution.photos.count(), 1)
        self.post('revoke')
        self.assertEqual(phone.get(url).status_code, 404)

    def test_expired_and_submitted_phone_tokens_are_rejected(self):
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() - 1000):
            expired = token_for(self.solution)
        self.assertEqual(self.client.get(reverse('solution-phone', args=[expired])).status_code, 404)
        token = token_for(self.solution)
        self.submit()
        self.assertEqual(self.client.get(reverse('solution-phone', args=[token])).status_code, 404)

    def test_phone_upload_requires_csrf_even_with_valid_token(self):
        phone = Client(enforce_csrf_checks=True)
        url = reverse('solution-phone', args=[token_for(self.solution)])
        phone.get(url)
        self.assertEqual(phone.post(url, {'photos': jpeg()}).status_code, 403)
        csrf = phone.cookies['csrftoken'].value
        self.assertEqual(phone.post(url, {'photos': jpeg(), 'csrfmiddlewaretoken': csrf}).status_code, 302)

    def test_invalid_batch_does_not_partially_save_and_limits_apply(self):
        bad = SimpleUploadedFile('bad.jpg', b'not an image', content_type='image/jpeg')
        self.assertContains(self.post('upload', photos=[jpeg(), bad]), 'Не удалось прочитать')
        self.assertFalse(self.solution.photos.exists())
        self.assertContains(self.post('upload', photos=[jpeg() for _ in range(13)]), 'до 12')
        self.assertFalse(self.solution.photos.exists())

    def test_rotate_reorder_delete_and_content_sealing(self):
        self.post('upload', photos=[jpeg(), jpeg()])
        first, second = list(self.solution.photos.all())
        self.post('up', photo=second.pk)
        self.assertEqual(self.solution.photos.first().pk, second.pk)
        self.post('rotate', photo=first.pk)
        first.refresh_from_db()
        with first.image.open('rb') as handle:
            image = Image.open(handle)
            self.assertEqual(image.size, (220, 160))
        self.post('delete', photo=second.pk)
        self.assertEqual(self.solution.photos.count(), 1)
        self.post('submit', text='Proof')
        self.assertContains(self.post('delete', photo=first.pk), 'зафиксировано')
        self.assertEqual(self.solution.photos.count(), 1)
        saved = self.client.post(f'/api/variants/attempts/{self.work.pk}/tasks/{self.row.pk}/save/',
            {'answer': 'replacement'}, content_type='application/json')
        self.assertGreaterEqual(saved.status_code, 400)

    def test_assessment_bounds_history_and_missing_criteria(self):
        self.submit()
        self.assertContains(self.post('assess', score='2'), 'Сначала откройте')
        self.post('reveal')
        for score in ['-1', '3', '1.5', 'nan']:
            self.post('assess', score=score)
        self.assertFalse(SolutionAssessment.objects.exists())
        self.post('assess', score='0')
        self.post('assess', score='2')
        self.assertEqual(list(self.solution.assessments.values_list('score', flat=True)), [2, 0])
        self.solution.reference_snapshot['assessment_criteria'] = ''
        self.solution.save(update_fields=['reference_snapshot'])
        self.assertContains(self.post('assess', score='1'), 'не добавил критерии')

    def test_ungraded_attempt_does_not_count_as_failure_or_difficulty(self):
        pending = Attempt.objects.create(user=self.user, task=self.task, score=None, is_correct=False,
            max_score=2, is_valid_attempt=True)
        self.assertTrue(pending.awaits_manual_grading)
        self.task.refresh_from_db()
        self.assertEqual(self.task.attempts_total, 0)
        self.assertEqual(rebuild_learning_state(self.user)['events'], 0)

    def test_qr_is_local_svg_and_does_not_send_token_to_external_provider(self):
        response = self.client.get(reverse('solution-qr', args=[self.solution.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/svg+xml')
        self.assertIn(b'<svg', response.content)

    def test_removing_photo_or_solution_removes_private_files_after_commit(self):
        self.post('upload', photos=jpeg())
        photo = self.solution.photos.get()
        storage, name = photo.image.storage, photo.image.name
        self.assertTrue(storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            self.post('delete', photo=photo.pk)
        self.assertFalse(storage.exists(name))
        self.post('upload', photos=jpeg())
        photo = self.solution.photos.get()
        name = photo.image.name
        with self.captureOnCommitCallbacks(execute=True):
            self.solution.delete()
        self.assertFalse(storage.exists(name))

