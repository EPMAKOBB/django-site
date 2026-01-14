from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.utils.text import slugify

from apps.recsys.models import ExamVersion


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    priority = 1.0

    def items(self):
        return ["home"]

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
