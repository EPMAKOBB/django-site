from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.utils.text import slugify

from apps.recsys.models import ExamVersion


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    priority = 1.0

    def items(self):
        return ["home", "tutors:catalog"]

    def location(self, item):
        return reverse(item)


class ExamVersionSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return ExamVersion.objects.filter(status=ExamVersion.Status.ACTIVE)

    def location(self, obj):
        slug = obj.slug or slugify(obj.name)
        return reverse("exam-page", kwargs={"exam_slug": slug})

    def lastmod(self, obj):
        return obj.updated_at


class TutorSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        from tutors.models import Tutor
        return Tutor.objects.filter(status=Tutor.Status.PUBLISHED, profile__user__is_active=True)
