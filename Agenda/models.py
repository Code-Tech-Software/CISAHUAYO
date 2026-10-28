"""Agenda / Calendario (pedido del 2026-10-18): los eventos del colegio que registra el administrador.

Cada evento es de un nivel educativo o de todo el colegio (`alcance`); los de todo el colegio se guardan una sola vez y
se muestran en todos los niveles. El color sale del alcance (con un texto que se lee bien sobre él). La agenda es
informativa: registrar un evento no cambia asistencias, calificaciones ni días sin clases.

Desde el 2026-10-27 un evento tiene tipo (vacaciones, exámenes, juntas, festivales, deportes: su icono y un filtro),
puede ser importante (un día antes se avisa a quienes lo ven: `AvisoAgenda` y notificación push) y puede repetirse: una
serie son eventos normales que comparten `serie` (se crean juntos; se corrigen o eliminan uno o «este y los siguientes»).
Cada persona puede suscribir su calendario del teléfono a su agenda con un enlace secreto (`SuscripcionCalendario`).
"""
import secrets

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.formats import date_format

from Alumnos.models import Alumno, Grado, Tutor

COLEGIO = 'COLEGIO'
# En la agenda el bachillerato se llama así y los eventos generales son de «Todos los niveles» (pedido del 2026-10-23)
ALCANCES = [*((clave, 'Bachillerato' if clave == 'PREPARATORIA' else nombre) for clave, nombre in Grado.NIVEL_CHOICES),
            (COLEGIO, 'Todos los niveles')]
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

# Los tipos de evento (2026-10-27): su nombre y su icono. Sin tipo, «Otro».
VACACIONES, EXAMENES, JUNTA, FESTIVAL, DEPORTES = 'VACACIONES', 'EXAMENES', 'JUNTA', 'FESTIVAL', 'DEPORTES'
TIPOS = [(VACACIONES, 'Vacaciones y días sin clases'), (EXAMENES, 'Exámenes y evaluaciones'), (JUNTA, 'Juntas y reuniones'),
         (FESTIVAL, 'Festivales y ceremonias'), (DEPORTES, 'Deportes')]
NOMBRE_DE_TIPO = {**dict(TIPOS), '': 'Otro'}
ICONO_DE_TIPO = {VACACIONES: 'sun', EXAMENES: 'notebook-pen', JUNTA: 'users', FESTIVAL: 'award', DEPORTES: 'flag', '': 'calendar'}


class EventoAgenda(models.Model):
    titulo = models.CharField('título', max_length=150)
    descripcion = models.TextField('descripción', max_length=2000, blank=True)
    alcance = models.CharField('alcance', max_length=20, choices=ALCANCES)
    tipo = models.CharField('tipo de evento', max_length=12, choices=TIPOS, blank=True)
    fecha_inicio = models.DateField('fecha de inicio')
    fecha_fin = models.DateField('fecha de finalización')
    todo_el_dia = models.BooleanField('todo el día', default=True)
    hora_inicio = models.TimeField('hora de inicio', null=True, blank=True)
    hora_fin = models.TimeField('hora de finalización', null=True, blank=True)
    lugar = models.CharField('lugar o ubicación', max_length=150, blank=True)
    importante = models.BooleanField('recordar un día antes', default=False,
                                     help_text='Un día antes se avisa en la campana (y en el teléfono) a quienes lo ven en su agenda.')
    # Cuándo se mandó su recordatorio (vacío: todavía no; se manda una sola vez)
    recordatorio_en = models.DateTimeField(null=True, blank=True)
    # Los eventos de una misma serie (se repite) comparten `serie`; `repeticion` lo dice en palabras («Cada lunes…»)
    serie = models.UUIDField(null=True, blank=True, db_index=True)
    repeticion = models.CharField(max_length=150, blank=True)

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
    def nombre_tipo(self):
        return NOMBRE_DE_TIPO.get(self.tipo, 'Otro')

    @property
    def icono(self):
        return ICONO_DE_TIPO.get(self.tipo, 'calendar')

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


class AvisoAgenda(models.Model):
    """El recordatorio de un evento importante para una persona que lo ve en su agenda (la sección «Agenda» de la
    campana): una cuenta del sistema, un tutor o un estudiante. Se crea un día antes (Agenda/recordatorios.py) y queda
    visto al abrir la agenda."""

    evento = models.ForeignKey(EventoAgenda, on_delete=models.CASCADE, related_name='avisos')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    alumno = models.ForeignKey(Alumno, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    creado = models.DateTimeField(auto_now_add=True, db_index=True)
    visto_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'recordatorio de la agenda'
        verbose_name_plural = 'recordatorios de la agenda'
        default_permissions = ()
        ordering = ['-creado', '-pk']
        constraints = [
            models.CheckConstraint(
                condition=(Q(usuario__isnull=False, tutor__isnull=True, alumno__isnull=True)
                           | Q(usuario__isnull=True, tutor__isnull=False, alumno__isnull=True)
                           | Q(usuario__isnull=True, tutor__isnull=True, alumno__isnull=False)),
                name='aviso_agenda_una_persona'),
            models.UniqueConstraint(fields=['evento', 'usuario'], condition=Q(usuario__isnull=False), name='aviso_agenda_usuario_unico'),
            models.UniqueConstraint(fields=['evento', 'tutor'], condition=Q(tutor__isnull=False), name='aviso_agenda_tutor_unico'),
            models.UniqueConstraint(fields=['evento', 'alumno'], condition=Q(alumno__isnull=False), name='aviso_agenda_alumno_unico'),
        ]

    def __str__(self):
        return f'Recordatorio de {self.evento}'


def nuevo_token():
    return secrets.token_urlsafe(32)


class SuscripcionCalendario(models.Model):
    """El enlace secreto con que el calendario del teléfono (Google, iPhone, Outlook) se suscribe a la agenda de una
    persona: lo mismo que ve en el sistema o en su portal, sin iniciar sesión. Quien lo tiene lo puede leer: por eso se
    puede cambiar por otro (el anterior deja de funcionar)."""

    token = models.CharField(max_length=64, unique=True, default=nuevo_token)
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='suscripcion_agenda')
    tutor = models.OneToOneField(Tutor, null=True, blank=True, on_delete=models.CASCADE, related_name='suscripcion_agenda')
    alumno = models.OneToOneField(Alumno, null=True, blank=True, on_delete=models.CASCADE, related_name='suscripcion_agenda')
    creada = models.DateTimeField(auto_now_add=True)
    usada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'suscripción al calendario'
        verbose_name_plural = 'suscripciones al calendario'
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=(Q(usuario__isnull=False, tutor__isnull=True, alumno__isnull=True)
                           | Q(usuario__isnull=True, tutor__isnull=False, alumno__isnull=True)
                           | Q(usuario__isnull=True, tutor__isnull=True, alumno__isnull=False)),
                name='suscripcion_agenda_una_persona'),
        ]

    def __str__(self):
        return 'Suscripción al calendario'
