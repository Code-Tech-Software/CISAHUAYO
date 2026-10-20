"""Agenda / Calendario (pedido del 2026-10-18): los eventos del colegio que registra el administrador.

Cada evento es de un nivel educativo o de todo el colegio (`alcance`); los de todo el colegio se guardan una sola vez y
se muestran en todos los niveles. El color sale del alcance (con un texto que se lee bien sobre él). La agenda es
informativa: registrar un evento no cambia asistencias, calificaciones ni días sin clases.
"""
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.formats import date_format

from Alumnos.models import Grado

COLEGIO = 'COLEGIO'
ALCANCES = [*Grado.NIVEL_CHOICES, (COLEGIO, 'Todo el colegio')]
NOMBRE_DE_ALCANCE = dict(ALCANCES)

# (fondo, texto): los colores de cada nivel que usa el colegio (pedido del 2026-10-20) y, encima, el texto que alcanza
# al menos 4.5:1 de contraste sobre ese fondo (entre paréntesis). En el morado de primaria el blanco no llega (4.39):
# lleva texto negro.
COLORES = {
    'PREESCOLAR': ('#48A8D0', '#111827'),     # azul (6.58)
    'PRIMARIA': ('#A1639C', '#000000'),       # morado (4.97)
    'SECUNDARIA': ('#C64A24', '#FFFFFF'),     # rojo (4.77)
    'PREPARATORIA': ('#507735', '#FFFFFF'),   # verde, el bachillerato (5.21)
    COLEGIO: ('#DFD327', '#111827'),          # amarillo, todos los niveles (11.39)
}


class EventoAgenda(models.Model):
    titulo = models.CharField('título', max_length=150)
    descripcion = models.TextField('descripción', max_length=2000, blank=True)
    alcance = models.CharField('alcance', max_length=20, choices=ALCANCES)
    fecha_inicio = models.DateField('fecha de inicio')
    fecha_fin = models.DateField('fecha de finalización')
    todo_el_dia = models.BooleanField('todo el día', default=True)
    hora_inicio = models.TimeField('hora de inicio', null=True, blank=True)
    hora_fin = models.TimeField('hora de finalización', null=True, blank=True)
    lugar = models.CharField('lugar o ubicación', max_length=150, blank=True)

    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'evento de la agenda'
        verbose_name_plural = 'eventos de la agenda'
        ordering = ['fecha_inicio', '-todo_el_dia', 'hora_inicio', 'titulo', 'pk']
        default_permissions = ()
        permissions = [('gestionar', 'Crear, editar y eliminar eventos de la agenda')]
        constraints = [
            models.CheckConstraint(condition=Q(fecha_fin__gte=F('fecha_inicio')), name='evento_agenda_fechas_en_orden'),
        ]
        indexes = [models.Index(fields=['fecha_inicio', 'fecha_fin'], name='evento_agenda_fechas')]

    def __str__(self):
        return self.titulo

    # --- Presentación -------------------------------------------------------------------------------------------
    @property
    def color(self):
        return COLORES[self.alcance][0]

    @property
    def color_texto(self):
        return COLORES[self.alcance][1]

    @property
    def nombre_alcance(self):
        return NOMBRE_DE_ALCANCE.get(self.alcance, self.alcance)

    @property
    def es_del_colegio(self):
        return self.alcance == COLEGIO

    @property
    def varios_dias(self):
        return self.fecha_fin > self.fecha_inicio

    @property
    def texto_de_fechas(self):
        if not self.varios_dias:
            return date_format(self.fecha_inicio, 'l j \\d\\e F \\d\\e Y').capitalize()
        mismo_anio = self.fecha_inicio.year == self.fecha_fin.year
        inicio = date_format(self.fecha_inicio, 'j \\d\\e F' if mismo_anio else 'j \\d\\e F \\d\\e Y')
        fin = date_format(self.fecha_fin, 'j \\d\\e F \\d\\e Y')
        return f'Del {inicio.lower()} al {fin.lower()}'          # los meses en minúsculas: «del 5 de octubre…»

    @property
    def texto_de_horario(self):
        if self.todo_el_dia or self.hora_inicio is None:
            return 'Todo el día'
        if self.hora_fin is None:
            return f'Desde las {self.hora_inicio:%H:%M}'
        return f'{self.hora_inicio:%H:%M} a {self.hora_fin:%H:%M}'

    @property
    def hora_corta(self):
        """La hora que se muestra junto al título en el calendario (vacía si es de todo el día)."""
        return '' if self.todo_el_dia or self.hora_inicio is None else f'{self.hora_inicio:%H:%M}'
