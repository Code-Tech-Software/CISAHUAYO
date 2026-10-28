"""Los recordatorios de la agenda en todas las páginas: la sección «Agenda» de la campana (contador y lista) para
cualquier cuenta del sistema y de los portales. Los genera Agenda/recordatorios.py; aquí solo se leen. Se calcula solo
si la plantilla lo usa."""
from django.db import DatabaseError
from django.urls import NoReverseMatch
from django.utils.functional import SimpleLazyObject

from .fuentes import Persona
from .recordatorios import datos_de_la_campana


def avisos_agenda(request):
    def calcular():
        try:
            persona = Persona.de_request(request)
            if persona is None:
                return {'activa': False}
            datos = datos_de_la_campana(persona)
        except (DatabaseError, NoReverseMatch):   # sin la migración o sin las rutas: el resto sigue funcionando
            return {'activa': False}
        return {'activa': True, 'url': persona.url('calendario'), **datos}

    return {'avisos_agenda': SimpleLazyObject(calcular)}
