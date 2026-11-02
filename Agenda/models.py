"""Agenda / Calendario (pedido del 2026-10-18): los eventos del colegio que registra el administrador.

Cada evento es de un nivel educativo, de varios o de todo el colegio (`alcance`); los de todo el colegio se guardan una
sola vez y se muestran en todos los niveles. El color sale del alcance (con un texto que se lee bien sobre él). La agenda
es informativa: registrar un evento no cambia asistencias, calificaciones ni días sin clases.

Desde el 2026-10-27 un evento tiene tipo (vacaciones, exámenes, juntas, festivales, deportes: su icono y un filtro),
puede ser importante (unos días antes se avisa a quienes lo ven: `AvisoAgenda` y notificación push) y puede repetirse:
una serie son eventos normales que comparten `serie` (se crean juntos; se corrigen o eliminan uno o «este y los
siguientes»). Cada persona puede suscribir su calendario del teléfono a su agenda con un enlace secreto
(`SuscripcionCalendario`).

Desde el 2026-11-02 (correcciones del diagnóstico):
- Varios niveles en un solo evento (`alcance` VARIOS, con sus niveles en `NivelEvento`) y, dentro de ellos, solo
  algunos grados o grupos (`grados`, `grupos`).
- Audiencia: el personal de esos niveles lo ve siempre; las familias y los estudiantes, solo si se marca.
- Un evento se puede cancelar (queda visible, tachado, con su motivo) y los cambios de fecha, hora o lugar se avisan.
- Archivos adjuntos (`AdjuntoEvento`) y confirmación de asistencia de las familias (`ConfirmacionAsistencia`).
- El comunicado con que se avisó del evento (`comunicado`): así no aparece dos veces en la agenda.
"""
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.formats import date_format

from Alumnos.models import ORDEN_NIVELES, Alumno, Grado, Grupo, Tutor

COLEGIO = 'COLEGIO'
VARIOS = 'VARIOS'
# En la agenda el bachillerato se llama así y los eventos generales son de «Todos los niveles» (pedido del 2026-10-23)
NIVELES = [(clave, 'Bachillerato' if clave == 'PREPARATORIA' else nombre) for clave, nombre in Grado.NIVEL_CHOICES]
NOMBRE_DE_NIVEL = dict(NIVELES)
ALCANCES = [*NIVELES, (VARIOS, 'Varios niveles'), (COLEGIO, 'Todos los niveles')]
NOMBRE_DE_ALCANCE = dict(ALCANCES)

# (fondo, texto): los colores de cada nivel que usa el colegio (pedido del 2026-10-20) y, encima, el texto que alcanza
# al menos 4.5:1 de contraste sobre ese fondo (entre paréntesis). En el morado de primaria el blanco no llega (4.39):
# lleva texto negro. Varios niveles: azul marino, distinto de todos (sus niveles van escritos y con su color al lado).
COLORES = {
    'PREESCOLAR': ('#48A8D0', '#111827'),     # azul (6.58)
    'PRIMARIA': ('#A1639C', '#000000'),       # morado (4.97)
    'SECUNDARIA': ('#C64A24', '#FFFFFF'),     # rojo (4.77)
    'PREPARATORIA': ('#507735', '#FFFFFF'),   # verde, el bachillerato (5.21)
    VARIOS: ('#1E3A8A', '#FFFFFF'),           # azul marino, varios niveles (10.36)
    COLEGIO: ('#DFD327', '#111827'),          # amarillo, todos los niveles (11.39)
}

# Los tipos de evento (2026-10-27): su nombre y su icono. Sin tipo, «Otro».
VACACIONES, EXAMENES, JUNTA, FESTIVAL, DEPORTES = 'VACACIONES', 'EXAMENES', 'JUNTA', 'FESTIVAL', 'DEPORTES'
TIPOS = [(VACACIONES, 'Vacaciones y días sin clases'), (EXAMENES, 'Exámenes y evaluaciones'), (JUNTA, 'Juntas y reuniones'),
         (FESTIVAL, 'Festivales y ceremonias'), (DEPORTES, 'Deportes')]
NOMBRE_DE_TIPO = {**dict(TIPOS), '': 'Otro'}
ICONO_DE_TIPO = {VACACIONES: 'sun', EXAMENES: 'notebook-pen', JUNTA: 'users', FESTIVAL: 'award', DEPORTES: 'flag', '': 'calendar'}

# Con cuánta anticipación se recuerda un evento importante
ANTICIPACIONES = [(1, 'Un día antes'), (3, 'Tres días antes'), (7, 'Una semana antes')]


def ruta_de_adjunto(instancia, nombre):
    """Nombre al azar (sin el del archivo original): la dirección no se puede adivinar ni se muestra; los archivos solo
    se entregan por la vista de la agenda, que revisa que quien los pide vea el evento (como en Comunicados)."""
    extension = Path(nombre).suffix.lower()[:10]
    return f'agenda/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}{extension}'


def texto_de_niveles(niveles):
    """«Primaria», «Secundaria y Bachillerato», «Preescolar, Primaria y Secundaria»."""
    nombres = [NOMBRE_DE_NIVEL[n] for n in ORDEN_NIVELES if n in niveles]
    return nombres[0] if len(nombres) == 1 else f'{", ".join(nombres[:-1])} y {nombres[-1]}' if nombres else ''


class EventoAgenda(models.Model):
    MAXIMO_ADJUNTOS = 5

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
    importante = models.BooleanField('recordar antes del evento', default=False,
                                     help_text='Se avisa en la campana (y en el teléfono) a quienes lo ven en su agenda.')
    recordar_dias = models.PositiveSmallIntegerField('con cuánta anticipación', choices=ANTICIPACIONES, default=1)
    # Cuándo se mandó su recordatorio (vacío: todavía no; se manda una sola vez)
    recordatorio_en = models.DateTimeField(null=True, blank=True)
    # Los eventos de una misma serie (se repite) comparten `serie`; `repeticion` lo dice en palabras («Cada lunes…»)
    serie = models.UUIDField(null=True, blank=True, db_index=True)
    repeticion = models.CharField(max_length=150, blank=True)

    # Para quién: el personal de sus niveles siempre; las familias y los estudiantes, si se marca. Con grados o grupos
    # (`por_grupos`), solo las familias y los estudiantes de esos grados o grupos (el personal lo ve igual).
    para_familias = models.BooleanField('lo ven las familias', default=True)
    para_estudiantes = models.BooleanField('lo ven los estudiantes', default=True)
    grados = models.ManyToManyField(Grado, blank=True, related_name='+', verbose_name='grados')
    grupos = models.ManyToManyField(Grupo, blank=True, related_name='+', verbose_name='grupos')
    por_grupos = models.BooleanField(default=False, editable=False)

    pide_confirmacion = models.BooleanField('pedir a las familias que confirmen su asistencia', default=False)
    # Cancelado: sigue en la agenda, tachado y con su motivo (eliminar lo quita de la agenda de todos)
    cancelado_en = models.DateTimeField(null=True, blank=True)
    cancelado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    motivo_cancelacion = models.CharField('motivo de la cancelación', max_length=200, blank=True)
    # El comunicado con que se avisó de este evento (se envió desde su detalle)
    comunicado = models.ForeignKey('Comunicados.Comunicado', null=True, blank=True, on_delete=models.SET_NULL, related_name='eventos_agenda')

    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'evento de la agenda'
        verbose_name_plural = 'eventos de la agenda'
        ordering = ['fecha_inicio', '-todo_el_dia', 'hora_inicio', 'titulo', 'pk']
        default_permissions = ()
        permissions = [('gestionar', 'Crear, editar y eliminar eventos de la agenda'),
                       ('gestionar_nivel', 'Crear, editar y eliminar los eventos de sus niveles')]
        constraints = [
            models.CheckConstraint(condition=Q(fecha_fin__gte=F('fecha_inicio')), name='evento_agenda_fechas_en_orden'),
        ]
        indexes = [models.Index(fields=['fecha_inicio', 'fecha_fin'], name='evento_agenda_fechas')]

    def __str__(self):
        return self.titulo

    # --- Para quién -----------------------------------------------------------------------------------------
    @property
    def niveles_del_evento(self):
        """Sus niveles, en orden escolar (los de VARIOS, de `niveles_varios`: conviene traerlos con prefetch)."""
        if self.alcance == COLEGIO:
            return list(ORDEN_NIVELES)
        if self.alcance == VARIOS:
            elegidos = {fila.nivel for fila in self.niveles_varios.all()} if self.pk else set()
            return [n for n in ORDEN_NIVELES if n in elegidos]
        return [self.alcance]

    @property
    def cancelado(self):
        return self.cancelado_en is not None

    # --- Presentación -------------------------------------------------------------------------------------------
    @property
    def color(self):
        return COLORES[self.alcance][0]

    @property
    def color_texto(self):
        return COLORES[self.alcance][1]

    @property
    def colores_de_niveles(self):
        """Con varios niveles, el color de cada uno (los puntos junto al título)."""
        return [COLORES[n][0] for n in self.niveles_del_evento] if self.alcance == VARIOS else []

    @property
    def nombre_alcance(self):
        if self.alcance == VARIOS:
            return texto_de_niveles(self.niveles_del_evento) or NOMBRE_DE_ALCANCE[VARIOS]
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
    def con_horario(self):
        return not self.todo_el_dia and self.hora_inicio is not None

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
        if not self.con_horario:
            return 'Todo el día'
        if self.varios_dias:
            # De varios días con horario: un solo bloque (como lo guarda el calendario del teléfono)
            fin = f' a las {self.hora_fin:%H:%M} del último día' if self.hora_fin else ''
            return f'Desde las {self.hora_inicio:%H:%M} del primer día{fin}'
        if self.hora_fin is None:
            return f'Desde las {self.hora_inicio:%H:%M}'
        return f'{self.hora_inicio:%H:%M} a {self.hora_fin:%H:%M}'

    @property
    def hora_corta(self):
        """La hora que se muestra junto al título en el calendario (vacía si es de todo el día)."""
        return f'{self.hora_inicio:%H:%M}' if self.con_horario else ''


class NivelEvento(models.Model):
    """Los niveles de un evento de varios niveles (alcance VARIOS). Uno de un nivel o de todo el colegio no los usa."""

    evento = models.ForeignKey(EventoAgenda, on_delete=models.CASCADE, related_name='niveles_varios')
    nivel = models.CharField(max_length=20, choices=Grado.NIVEL_CHOICES)

    class Meta:
        verbose_name = 'nivel de un evento'
        verbose_name_plural = 'niveles de los eventos'
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['evento', 'nivel'], name='nivel_evento_unico')]

    def __str__(self):
        return self.nivel


class AdjuntoEvento(models.Model):
    """Un archivo del evento (la convocatoria, el permiso para firmar…): fotos y PDF de hasta 5 MB. Los eventos de una
    serie comparten el mismo archivo guardado."""

    evento = models.ForeignKey(EventoAgenda, on_delete=models.CASCADE, related_name='adjuntos')
    archivo = models.FileField(upload_to=ruta_de_adjunto, max_length=200)
    nombre_original = models.CharField(max_length=200)
    tipo = models.CharField(max_length=80)
    tamano = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'archivo de un evento'
        verbose_name_plural = 'archivos de los eventos'
        default_permissions = ()
        ordering = ['pk']

    def __str__(self):
        return self.nombre_original

    @property
    def es_imagen(self):
        return self.tipo.startswith('image/')


class ConfirmacionAsistencia(models.Model):
    """La respuesta de una familia a «¿Asistirán?» en un evento que lo pide. Se puede cambiar hasta que empiece."""

    MAXIMO_DE_PERSONAS = 10

    evento = models.ForeignKey(EventoAgenda, on_delete=models.CASCADE, related_name='confirmaciones')
    tutor = models.ForeignKey(Tutor, on_delete=models.CASCADE, related_name='+')
    asistira = models.BooleanField()
    personas = models.PositiveSmallIntegerField(default=1)
    respondido_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'confirmación de asistencia'
        verbose_name_plural = 'confirmaciones de asistencia'
        default_permissions = ()
        ordering = ['-respondido_en', '-pk']
        constraints = [models.UniqueConstraint(fields=['evento', 'tutor'], name='confirmacion_una_por_familia')]

    def __str__(self):
        return f'{self.tutor} · {"asistirá" if self.asistira else "no asistirá"}'


class AvisoAgenda(models.Model):
    """Una novedad de un evento para una persona que lo ve en su agenda (la sección «Agenda» de la campana): una cuenta
    del sistema, un tutor o un estudiante. El recordatorio de un evento importante (Agenda/recordatorios.py), un cambio
    de fecha, hora o lugar o su cancelación. Cada persona tiene a lo más una por evento (la más reciente) y queda vista
    al abrir la agenda."""

    RECORDATORIO, CAMBIO, CANCELADO = 'RECORDATORIO', 'CAMBIO', 'CANCELADO'
    TIPOS = [(RECORDATORIO, 'Recordatorio'), (CAMBIO, 'Cambio'), (CANCELADO, 'Cancelación')]

    evento = models.ForeignKey(EventoAgenda, on_delete=models.CASCADE, related_name='avisos')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    alumno = models.ForeignKey(Alumno, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    tipo = models.CharField(max_length=12, choices=TIPOS, default=RECORDATORIO)
    texto = models.CharField(max_length=200, blank=True)   # qué cambió («Nueva fecha: …») o el motivo de la cancelación
    creado = models.DateTimeField(auto_now_add=True, db_index=True)
    visto_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'aviso de la agenda'
        verbose_name_plural = 'avisos de la agenda'
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
        return f'{self.get_tipo_display()} de {self.evento}'


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
