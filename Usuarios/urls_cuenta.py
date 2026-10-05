"""Las páginas de la propia cuenta (cualquier usuario con sesión): datos personales y contraseña."""
from django.urls import path

from . import views

app_name = 'cuenta'

urlpatterns = [
    path('', views.cuenta_perfil, name='perfil'),
    path('contrasena/', views.cuenta_contrasena, name='contrasena'),
]
