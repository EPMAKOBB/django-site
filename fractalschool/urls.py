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
from django.contrib import admin
from django.urls import include, path

from apps.recsys import views as recsys_views
from .views import HomeView

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('courses/', include(('courses.urls', 'courses'), namespace='courses')),
    path('applications/', include(('applications.urls', 'applications'), namespace='applications')),

    path('', include('apps.recsys.api.urls')),


    path('recsys/dashboard/', recsys_views.dashboard, name='recsys_dashboard'),
    path('recsys/user/<int:user_id>/', recsys_views.teacher_user, name='recsys_teacher_user'),
    path('tasks/', recsys_views.tasks_list, name='tasks_list'),

]
