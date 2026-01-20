"""
URL configuration for fractalschool project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os
from django.contrib import admin
from django.urls import include, path
from django.contrib.sitemaps.views import sitemap
from django.conf import settings
from django.conf.urls.static import static

from apps.recsys import views as recsys_views
from .views import HomeView, robots_txt
from .sitemaps import ExamVersionSitemap, StaticViewSitemap

sitemaps = {
    "static": StaticViewSitemap,
    "exams": ExamVersionSitemap,
}

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path("robots.txt", robots_txt, name="robots-txt"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('courses/', include(('courses.urls', 'courses'), namespace='courses')),
    path('applications/', include(('applications.urls', 'applications'), namespace='applications')),
    path('parser/', include(('parser_tasks.urls', 'parser_tasks'), namespace='parser_tasks')),

    path('', include('apps.recsys.api.urls')),

    path('exams/<slug:exam_slug>/', recsys_views.exam_page, name='exam-page'),
    path('exams/<slug:exam_slug>/public/', recsys_views.exam_public_blocks, name='exam-public-blocks'),
    path('exams/<slug:exam_slug>/progress/', recsys_views.exam_progress_data, name='exam-progress-data'),
    path(
        'exams/<slug:exam_slug>/<slug:type_slug>/',
        recsys_views.exam_type_page,
        name='exam-type-page',
    ),
    path('variants/<slug:slug>/', recsys_views.variant_page, name='variant-page'),

    path('recsys/dashboard/', recsys_views.dashboard, name='recsys_dashboard'),
    path('recsys/user/<int:user_id>/', recsys_views.teacher_user, name='recsys_teacher_user'),
    path('tasks/upload/', recsys_views.task_upload, name='tasks_upload'),
    path('tasks/', recsys_views.tasks_list, name='tasks_list'),

]

# Serve uploaded media locally during development when S3 is not configured
# Локальная подача media, когда не используем S3 (напр. Railway volume /app/media)
if not getattr(settings, "USE_S3_MEDIA", False):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
