from django.urls import path

from . import views

app_name = 'panel'

urlpatterns = [
    path('panel/estudiantes-en-seguimiento/', views.estudiantes_en_seguimiento, name='seguimiento'),
    path('ajustes/seguimiento/', views.criterios, name='criterios'),
]
