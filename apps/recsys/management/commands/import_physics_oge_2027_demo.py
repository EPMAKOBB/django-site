"""Import the reviewed demo source; template publication is a separate operation."""
import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from apps.recsys.models import (ExamVersion,Source,SourceVariant,Task,TaskTag,Skill,
    TaskSkill,TaskPlacement,TaskAttachment)
from apps.recsys.service_utils.grading import grade_answer


class Command(BaseCommand):
    help = 'Import all 22 approved physics demo tasks, references and criteria; preview by default.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--publish-tasks', action='store_true')
        parser.add_argument('--expect-database')
        parser.add_argument('--expect-user')

    @transaction.atomic
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_user, current_database()')
            role, database = cursor.fetchone()
            if options['apply'] and (options['expect_database'], options['expect_user']) != (database, role):
                raise CommandError('Apply requires the exact expected database and current database user.')
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('physics-oge-2027-demo-import'))")
        data = json.loads((Path(settings.BASE_DIR)/'scripts/data/physics_oge_2027_demo.json').read_text(encoding='utf-8'))
        catalog = json.loads((Path(settings.BASE_DIR)/'scripts/data/physics_oge_2027.json').read_text(encoding='utf-8'))
        if [item['number'] for item in data['tasks']] != list(range(1,23)):
            raise CommandError('Expected one task for every position 1–22.')
        exam = ExamVersion.objects.get(slug=data['exam_slug'])
        source = Source.objects.get(slug=data['source_slug'],exam_version=exam)
        variant = SourceVariant.objects.select_for_update().get(source=source,slug=data['source_variant_slug'])
        if variant.label not in ('Демоверсия 2027',data['name']):
            raise CommandError('The source variant has an author title; not overwritten.')
        variant.label=data['name'];variant.save(update_fields=['label','updated_at'])
        task_ids=[];created_ids=[]
        for entry in data['tasks']:
            n=entry['number'];typ=exam.task_types.get(display_order=n)
            if (typ.scoring_scheme,typ.max_score)!=(catalog['types'][n-1]['scoring_scheme'],catalog['types'][n-1]['max_score']):
                raise CommandError(f'Type {n} grading does not match the reviewed specification.')
            defaults={'subject':exam.subject,'exam_version':exam,'type':typ,'source':source,'source_variant':variant,
                'title':entry['title'],'description':entry['description'],'correct_answer':entry['correct_answer'],
                'reference_solution':entry['reference_solution'],'assessment_criteria':entry['assessment_criteria'],
                'rendering_strategy':'markdown','expected_time_seconds':catalog['types'][n-1]['minutes']*60,
                'default_payload':{'source_pages':entry['source_pages'],'source_demo_sha256':data['source_demo_sha256']}}
            task,created=Task.objects.get_or_create(slug=entry['slug'],defaults={**defaults,'status':'draft'})
            if not created:
                for field,value in defaults.items():
                    if getattr(task,field)!=value:
                        raise CommandError(f'Task {task.slug} has different author content: {field}.')
                if task.status not in ('draft','published'):
                    raise CommandError(f'Task {task.slug} has an incompatible workflow status.')
            tags=set()
            for code in entry['topic_codes']:
                tags.add(TaskTag.objects.get(subject=exam.subject,slug='phys-oge-topic-'+code.replace('.','-')).pk)
                tags.add(TaskTag.objects.get(subject=exam.subject,slug='phys-oge-section-'+code.split('.')[0]).pk)
            # The limited writer can read the catalog and tags but need not read
            # every newer through-table. Validate content against the reviewed
            # specification rather than requesting broader database privileges.
            sections=set(catalog['types'][n-1]['sections'])
            permitted_codes={topic['code'] for topic in catalog['topics'] if int(topic['code'].split('.')[0]) in sections}
            if not set(entry['topic_codes'])<=permitted_codes:
                raise CommandError(f'Task {n} has topics outside its type specification.')
            if created:
                task.tags.set(tags)
                for index in entry['skill_indexes']:
                    TaskSkill.objects.create(task=task,skill=Skill.objects.get(subject=exam.subject,name=catalog['skills'][index-1]))
            elif set(task.tags.values_list('pk',flat=True))!=tags:
                raise CommandError(f'Task {n}: author topic changes found.')
            task.full_clean()
            if n<=16:
                if grade_answer(typ.scoring_scheme,task.correct_answer,entry['correct_answer'],max_score=typ.max_score)!=(typ.max_score,True):
                    raise CommandError(f'Task {n}: answer key does not receive full credit.')
            elif not task.reference_solution or not task.assessment_criteria:
                raise CommandError(f'Task {n}: missing written-answer reference/criteria.')
            placement,_=TaskPlacement.objects.get_or_create(task=task,task_type=typ,defaults={'status':'draft'})
            for page in (4,5):
                item=next(asset for asset in data['assets'] if asset['file']==f'reference-page-{page}.png')
                attachment,was_created=TaskAttachment.objects.get_or_create(task=task,label=f'Справочные данные (лист {page-3})',
                    defaults={'kind':'file','file':item['path'],'order':page-4,
                              'download_name_override':f'Справочные данные ОГЭ 2027 — стр. {page}.png'})
                if not was_created and attachment.file.name!=item['path']:
                    raise CommandError('Reference attachment was changed by an author.')
            if options['publish_tasks']:
                task.status='published';task.save(update_fields=['status','updated_at'])
                placement.status='active';placement.save(update_fields=['status','updated_at'])
            task_ids.append(task.pk)
            if created:created_ids.append(task.pk)
        self.stdout.write(json.dumps({'applied':options['apply'],'database_user':role,'source_variant_id':variant.pk,
            'source_variant_name':variant.label,'tasks':task_ids,'created':created_ids,
            'published':options['publish_tasks'],'max_primary':sum(t['max_score'] for t in catalog['types'])},ensure_ascii=False,indent=2))
        if not options['apply']:transaction.set_rollback(True)
