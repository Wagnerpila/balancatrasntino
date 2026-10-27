from django.urls import path
from .views import notification, keepalive

urlpatterns = [
    path('notification/', notification, name='notification'),
    path('keepalive/', keepalive, name='keepalive'),
]
