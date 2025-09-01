from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Attempt, SkillMastery, TypeMastery, TaskSkill

@receiver(post_save, sender=Attempt)
def update_mastery_on_attempt(sender, instance, created, **kwargs):
    if not created:
        return
    user = instance.user
    task = instance.task
    for task_skill in TaskSkill.objects.filter(task=task):
        skill_mastery, _ = SkillMastery.objects.get_or_create(user=user, skill=task_skill.skill)
        if instance.is_correct:
            skill_mastery.mastery += task_skill.weight
        skill_mastery.confidence += 1
        skill_mastery.save()
    type_mastery, _ = TypeMastery.objects.get_or_create(user=user, task_type=task.type)
    if instance.is_correct:
        type_mastery.mastery += 1
    type_mastery.confidence += 1
    type_mastery.save()
