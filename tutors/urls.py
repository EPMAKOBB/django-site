from django.urls import path
from . import views
app_name = 'tutors'
urlpatterns = [
    path('', views.catalog, name='catalog'),
    path('manage/', views.manage, name='manage'),
    path('bookings/<int:pk>/action/', views.booking_action, name='booking-action'),
    path('booking/<uuid:token>/', views.booking_status, name='booking-status'),
    path('<slug:slug>/photo/', views.photo, name='photo'),
    path('<slug:slug>/calendar/', views.calendar, name='calendar'),
    path('<slug:slug>/book/<int:offering_id>/', views.book, name='book'),
    path('<slug:slug>/', views.detail, name='detail'),
]
