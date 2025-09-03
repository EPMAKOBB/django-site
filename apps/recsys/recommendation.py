from .models import Task, SkillMastery


def recommend_tasks(user, exam_version=None):
    """Return tasks sorted by user's mastery (ascending).

    If ``exam_version`` is provided, only tasks for that exam version
    are considered.
    """
    tasks = Task.objects.all()
    if exam_version is not None:
        tasks = tasks.filter(type__exam_version=exam_version)
    def score(task):
        total = 0
        count = 0
        for skill in task.skills.all():
            mastery = SkillMastery.objects.filter(user=user, skill=skill).first()
            if mastery:
                total += mastery.mastery
                count += 1
        return total / count if count else 0
    return sorted(tasks, key=score)
