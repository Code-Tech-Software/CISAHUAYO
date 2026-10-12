from django.urls import path

from . import views

app_name = 'ajustes'

urlpatterns = [
    path('', views.ajustes, name='inicio'),
]
