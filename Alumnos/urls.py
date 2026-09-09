from django.urls import path

from . import views

urlpatterns = [
    path( 'asistencia/rapida/',views.asistencia_rapida,name='asistencia_rapida'),

]
