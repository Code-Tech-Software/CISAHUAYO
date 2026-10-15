from django.urls import path

from . import views

app_name = 'portal_tutores'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('estudiantes/<int:pk>/', views.estudiante, name='estudiante'),
    path('salir/', views.salir, name='salir'),
]
