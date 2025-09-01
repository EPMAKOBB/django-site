from .models import Task, SkillMastery


def recommend_tasks(user):
    """Return tasks sorted by user's mastery (ascending)."""
    tasks = Task.objects.all()
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
