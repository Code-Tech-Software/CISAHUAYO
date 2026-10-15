from django.urls import path

from . import views

app_name = 'portal_estudiantes'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('salir/', views.salir, name='salir'),
]
