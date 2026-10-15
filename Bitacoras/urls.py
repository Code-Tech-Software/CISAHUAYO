from django.urls import path

from . import views

app_name = 'bitacoras'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('nueva/', views.crear, name='crear'),
    path('opciones/', views.opciones, name='opciones'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/editar/', views.editar, name='editar'),
    path('<int:pk>/anular/', views.anular, name='anular'),
    path('estudiantes/<int:pk>/', views.estudiante, name='estudiante'),
]
