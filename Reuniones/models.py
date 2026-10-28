"""Reuniones con familias (pedido del 2026-10-19): las citas que los tutores solicitan (casi siempre por teléfono) para
reunirse con Dirección, Coordinación académica, Prefectura o un docente, desde la llamada hasta el seguimiento de los
acuerdos.

- **Configuración** (`ConfiguracionReuniones`, `MotivoReunion`, `SalaReunion`): Ajustes › Reuniones (solo el
  administrador). Un motivo o una sala ya usados no se borran: se desactivan.
- **Reunión** (`Reunion`): la solicitud con su folio, quién la registró y cuándo, el tutor solicitante y su teléfono, con
  quién quiere reunirse, el motivo, la prioridad, los horarios que propuso el tutor y las observaciones internas. Al
  programarse lleva fecha, horario, sala y responsable. Registrar la llamada nunca confirma la cita.
- **Quiénes** (`EstudianteEnReunion`, `TutorEnReunion`, `ParticipanteReunion`): los estudiantes (con su grupo cuando se
  pidió), los tutores que asisten y el personal: docentes, acompañantes directivos y otro personal, cada uno con su
  confirmación y su asistencia real. Toda reunión con un docente necesita un acompañante directivo (reglas.py).
- **Historial** (`CambioDeFecha`, `ContactoReunion`, `EventoReunion`): cada reprogramación con la fecha anterior y la
  nueva, cada confirmación o aviso a la familia (quién lo recibió, cuándo y por qué medio) y la bitácora. Nada se
  sobrescribe.
- **Minuta y acuerdos** (`Minuta`, `Acuerdo`, `SeguimientoAcuerdo`, `AdjuntoReunion`): lo que pasó en la reunión, las
  notas internas confidenciales (nunca se muestran al tutor), los acuerdos con su responsable, su fecha límite y su
  seguimiento, y los documentos (también la evidencia de firma).
- **Notificaciones** (`NotificacionReunion`): los avisos de la campana, sin motivos ni notas.
- **Desde el portal** (2026-10-28): las indicaciones para la familia (`Reunion.indicaciones`), el «Leí la minuta y los
  acuerdos» de cada tutor (`TutorEnReunion.enterado_minuta_en`) y el avance que reporta la familia de un acuerdo
  (`SeguimientoAcuerdo` con `tutor`), que el responsable revisa.

La reunión es un registro aparte: no cambia calificaciones, asistencias ni genera sanciones.
"""
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from Alumnos.models import Alumno, HorarioMateria, Inscripcion, Tutor

DIAS = HorarioMateria.DIA_CHOICES
NOMBRE_DE_DIA = dict(DIAS)


def _dias_habiles():
    return [0, 1, 2, 3, 4]


def _ruta(carpeta, nombre):
    """Nombre al azar (sin el del archivo original): la dirección no se puede adivinar; los archivos solo se entregan
    por las vistas del módulo, que revisan el permiso."""
    extension = Path(nombre).suffix.lower()[:10]
    return f'reuniones/{carpeta}/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}{extension}'


def ruta_de_adjunto(instancia, nombre):
    return _ruta('documentos', nombre)


def ruta_de_evidencia(instancia, nombre):
    return _ruta('seguimiento', nombre)


# ---------------------------------------------------------------------------
# Configuración (Ajustes › Reuniones)
# ---------------------------------------------------------------------------
class ConfiguracionReuniones(models.Model):
    """Una sola fila (pk=1): horario de atención, duración y anticipación de los avisos."""

    dias = models.JSONField('días de atención', default=_dias_habiles)
    hora_apertura = models.TimeField('desde', default=time(8, 0))
    hora_cierre = models.TimeField('hasta', default=time(15, 0))
    duracion = models.PositiveSmallIntegerField(
        'duración predeterminada (minutos)', default=30, validators=[MinValueValidator(10), MaxValueValidator(240)])
    recordatorio_horas = models.PositiveSmallIntegerField(
        'recordatorio previo (horas antes)', default=24, validators=[MinValueValidator(1), MaxValueValidator(168)],
        help_text='Cuántas horas antes de la reunión se recuerda a los participantes y a la familia.')
    aviso_acuerdos_dias = models.PositiveSmallIntegerField(
        'aviso de acuerdos por vencer (días antes)', default=2, validators=[MaxValueValidator(30)],
        help_text='Cuántos días antes de su fecha límite se avisa de un acuerdo pendiente.')
    espera_dias = models.PositiveSmallIntegerField(
        'plazo para programar una solicitud (días hábiles)', default=3, validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text='Si una solicitud no se programa en ese plazo, se avisa a quien la atiende. Las urgentes, el mismo día.')
    modificado = models.DateTimeField(auto_now=True)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'configuración de reuniones'
        verbose_name_plural = 'configuración de reuniones'
        default_permissions = ()

    def __str__(self):
        return 'Configuración de reuniones con familias'

    @classmethod
    def actual(cls):
        configuracion, _ = cls.objects.get_or_create(pk=1)
        return configuracion

    @property
    def nombres_de_dias(self):
        return [NOMBRE_DE_DIA[d] for d, _ in DIAS if d in (self.dias or [])]


class _Catalogo(models.Model):
    nombre = models.CharField('nombre', max_length=80, unique=True)
    activo = models.BooleanField('activo', default=True, help_text='Solo los activos se ofrecen en las solicitudes nuevas.')
    orden = models.PositiveSmallIntegerField('orden', default=0, help_text='Los de número menor aparecen primero.')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['orden', 'nombre']
        default_permissions = ()

    def __str__(self):
        return self.nombre


class MotivoReunion(_Catalogo):
    class Meta(_Catalogo.Meta):
        verbose_name = 'motivo de reunión'
        verbose_name_plural = 'motivos de reunión'


class SalaReunion(_Catalogo):
    ubicacion = models.CharField('ubicación', max_length=120, blank=True)

    class Meta(_Catalogo.Meta):
        verbose_name = 'lugar o sala'
        verbose_name_plural = 'lugares y salas'


# ---------------------------------------------------------------------------
# La reunión
# ---------------------------------------------------------------------------
class Reunion(models.Model):
    SOLICITADA, PENDIENTE, PROGRAMADA, CONFIRMADA = 'SOLICITADA', 'PENDIENTE', 'PROGRAMADA', 'CONFIRMADA'
    EN_CURSO, REALIZADA, CANCELADA, NO_REALIZADA = 'EN_CURSO', 'REALIZADA', 'CANCELADA', 'NO_REALIZADA'
    ESTADOS = [
        (SOLICITADA, 'Solicitada'),
        (PENDIENTE, 'Pendiente de programación'),
        (PROGRAMADA, 'Programada, pendiente de confirmación'),
        (CONFIRMADA, 'Confirmada'),
        (EN_CURSO, 'En curso'),
        (REALIZADA, 'Realizada'),
        (CANCELADA, 'Cancelada'),
        (NO_REALIZADA, 'No realizada por inasistencia'),
    ]
    SIN_PROGRAMAR = (SOLICITADA, PENDIENTE)
    ACTIVAS = (PROGRAMADA, CONFIRMADA, EN_CURSO)          # ocupan su horario y su sala
    ABIERTAS = (SOLICITADA, PENDIENTE, PROGRAMADA, CONFIRMADA, EN_CURSO)

    DIRECCION, COORDINACION, PREFECTURA, DOCENTE = 'DIRECCION', 'COORDINACION', 'PREFECTURA', 'DOCENTE'
    AREAS = [(DIRECCION, 'Dirección'), (COORDINACION, 'Coordinación académica'), (PREFECTURA, 'Prefectura'), (DOCENTE, 'Docente')]

    NORMAL, ALTA, URGENTE = 'NORMAL', 'ALTA', 'URGENTE'
    PRIORIDADES = [(NORMAL, 'Normal'), (ALTA, 'Alta'), (URGENTE, 'Urgente')]

    folio = models.CharField('folio', max_length=20, unique=True, blank=True, editable=False)
    # La solicitud (lo que se anota al atender la llamada)
    tutor = models.ForeignKey(Tutor, on_delete=models.PROTECT, related_name='reuniones_solicitadas', verbose_name='tutor solicitante')
    telefono = models.CharField('teléfono de contacto', max_length=20)
    telefono_verificado = models.BooleanField('teléfono verificado', default=False)
    area = models.CharField('quiere reunirse con', max_length=14, choices=AREAS)
    motivo = models.ForeignKey(MotivoReunion, on_delete=models.PROTECT, related_name='reuniones', verbose_name='motivo')
    descripcion = models.TextField('descripción de la solicitud', max_length=2000)
    prioridad = models.CharField('prioridad', max_length=8, choices=PRIORIDADES, default=NORMAL)
    propuestas = models.JSONField('horarios propuestos por el tutor', default=list, blank=True)   # [{fecha, desde, hasta}]
    observaciones_internas = models.TextField('observaciones internas', max_length=2000, blank=True)
    # Lo que la familia debe saber (se ve en su portal, en el recordatorio y en el archivo de calendario)
    indicaciones = models.TextField('indicaciones para la familia', max_length=500, blank=True)

    estado = models.CharField('estado', max_length=14, choices=ESTADOS, default=SOLICITADA, db_index=True)
    # La cita
    fecha = models.DateField('fecha', null=True, blank=True, db_index=True)
    hora_inicio = models.TimeField('hora de inicio', null=True, blank=True)
    hora_fin = models.TimeField('hora de término', null=True, blank=True)
    sala = models.ForeignKey(SalaReunion, null=True, blank=True, on_delete=models.PROTECT, related_name='reuniones', verbose_name='lugar o sala')
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='reuniones_a_cargo', verbose_name='responsable de la reunión')
    confirmacion_tutor = models.ForeignKey('ContactoReunion', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                           verbose_name='confirmación del tutor')
    reunion_anterior = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='siguientes',
                                         verbose_name='reunión anterior')
    # Realización
    iniciada_en = models.DateTimeField('inició', null=True, blank=True)
    terminada_en = models.DateTimeField('terminó', null=True, blank=True)
    # Cancelación o inasistencia
    motivo_cierre = models.TextField('motivo de la cancelación o de la inasistencia', max_length=1000, blank=True)
    cerrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cerrada_en = models.DateTimeField(null=True, blank=True)

    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+',
                                       verbose_name='registró')
    creada = models.DateTimeField('solicitada', auto_now_add=True)
    modificada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'reunión con familia'
        verbose_name_plural = 'reuniones con familias'
        ordering = ['-creada', '-pk']
        default_permissions = ()
        permissions = [
            ('participar', 'Ver las reuniones en que participa y confirmar su disponibilidad'),
            ('registrar', 'Registrar solicitudes, consultar la disponibilidad y programar citas'),
            ('gestionar', 'Gestionar las reuniones de sus niveles'),
            ('acompanar', 'Acompañar como directivo las reuniones con docentes'),
            ('confidencial', 'Ver y escribir las notas internas confidenciales'),
            ('todo', 'Reuniones de todo el colegio'),
            ('configurar', 'Configurar las reuniones (motivos, salas y horarios)'),
        ]
        indexes = [models.Index(fields=['fecha', 'hora_inicio'], name='reunion_fecha_hora')]
        constraints = [
            models.CheckConstraint(
                condition=Q(hora_inicio__isnull=True) | Q(hora_fin__isnull=True) | Q(hora_fin__gt=models.F('hora_inicio')),
                name='reunion_horario_en_orden'),
        ]

    def __str__(self):
        return self.folio or f'Reunión {self.pk}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.folio:   # el folio sale del número de la reunión: RF-2026-00012
            self.folio = f'RF-{self.creada:%Y}-{self.pk:05d}'
            Reunion.objects.filter(pk=self.pk).update(folio=self.folio)

    # --- estado -------------------------------------------------------------------------------------------------
    @property
    def nombre_estado(self):
        return self.get_estado_display()

    @property
    def abierta(self):
        return self.estado in self.ABIERTAS

    @property
    def programada(self):
        return self.fecha is not None and self.hora_inicio is not None and self.hora_fin is not None

    @property
    def inicio(self):
        if not self.programada:
            return None
        return timezone.make_aware(datetime.combine(self.fecha, self.hora_inicio))

    @property
    def fin(self):
        if not self.programada:
            return None
        return timezone.make_aware(datetime.combine(self.fecha, self.hora_fin))

    @property
    def duracion(self):
        if not self.programada:
            return None
        return int((datetime.combine(self.fecha, self.hora_fin) - datetime.combine(self.fecha, self.hora_inicio)) / timedelta(minutes=1))

    # --- para el calendario del mes (Agenda/calendario.py) -------------------------------------------------------
    @property
    def fecha_inicio(self):
        return self.fecha

    @property
    def fecha_fin(self):
        return self.fecha

    todo_el_dia = False

    @property
    def titulo(self):
        return self.folio


class EstudianteEnReunion(models.Model):
    reunion = models.ForeignKey(Reunion, on_delete=models.CASCADE, related_name='estudiantes')
    alumno = models.ForeignKey(Alumno, on_delete=models.PROTECT, related_name='reuniones_con_familia', verbose_name='estudiante')
    # Su grupo cuando se solicitó (alcance por nivel, filtros y lo que se ve aunque después cambie de grupo)
    inscripcion = models.ForeignKey(Inscripcion, null=True, blank=True, on_delete=models.PROTECT, related_name='reuniones_con_familia')

    class Meta:
        verbose_name = 'estudiante de una reunión'
        verbose_name_plural = 'estudiantes de las reuniones'
        ordering = ['reunion', 'alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre']
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['reunion', 'alumno'], name='reunion_estudiante_unico')]

    def __str__(self):
        return f'{self.alumno} · {self.reunion}'


PRESENTE, AUSENTE = 'PRESENTE', 'AUSENTE'
ASISTENCIAS = [(PRESENTE, 'Asistió'), (AUSENTE, 'No asistió')]


class TutorEnReunion(models.Model):
    reunion = models.ForeignKey(Reunion, on_delete=models.CASCADE, related_name='tutores')
    tutor = models.ForeignKey(Tutor, on_delete=models.PROTECT, related_name='reuniones_con_familia')
    solicitante = models.BooleanField('solicitó la reunión', default=False)
    asistencia = models.CharField('asistencia', max_length=10, choices=ASISTENCIAS, blank=True)
    # «Leí la minuta y los acuerdos» desde su portal (vale si es posterior a la última edición de la minuta)
    enterado_minuta_en = models.DateTimeField('leyó la minuta', null=True, blank=True)

    class Meta:
        verbose_name = 'tutor de una reunión'
        verbose_name_plural = 'tutores de las reuniones'
        ordering = ['reunion', '-solicitante', 'tutor__nombre']
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['reunion', 'tutor'], name='reunion_tutor_unico')]

    def __str__(self):
        return f'{self.tutor} · {self.reunion}'


class ParticipanteReunion(models.Model):
    DOCENTE, ACOMPANANTE, PERSONAL = 'DOCENTE', 'ACOMPANANTE', 'PERSONAL'
    PAPELES = [(DOCENTE, 'Docente'), (ACOMPANANTE, 'Acompañante directivo'), (PERSONAL, 'Personal escolar')]
    PENDIENTE, CONFIRMADA, NO_DISPONIBLE = 'PENDIENTE', 'CONFIRMADA', 'NO_DISPONIBLE'
    CONFIRMACIONES = [(PENDIENTE, 'Sin confirmar'), (CONFIRMADA, 'Disponible'), (NO_DISPONIBLE, 'No disponible')]

    reunion = models.ForeignKey(Reunion, on_delete=models.CASCADE, related_name='participantes')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='participaciones_en_reuniones')
    papel = models.CharField('papel', max_length=12, choices=PAPELES)
    # Se conserva aunque salga de la reunión (sustituido o quitado): el historial no se borra
    activo = models.BooleanField(default=True)
    retirado_en = models.DateTimeField(null=True, blank=True)
    retirado_motivo = models.CharField(max_length=300, blank=True)
    sustituye_a = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='sustitutos')

    confirmacion = models.CharField('disponibilidad', max_length=14, choices=CONFIRMACIONES, default=PENDIENTE)
    confirmacion_en = models.DateTimeField(null=True, blank=True)
    confirmacion_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    confirmacion_nota = models.CharField('nota', max_length=300, blank=True)

    asistencia = models.CharField('asistencia', max_length=10, choices=ASISTENCIAS, blank=True)
    presente_toda = models.BooleanField('estuvo durante toda la reunión', default=False)

    agregado_en = models.DateTimeField(auto_now_add=True)
    agregado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'participante de una reunión'
        verbose_name_plural = 'participantes de las reuniones'
        ordering = ['reunion', 'papel', 'pk']
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['reunion', 'usuario'], condition=Q(activo=True), name='reunion_participante_activo_unico'),
        ]

    def __str__(self):
        return f'{self.usuario} · {self.get_papel_display()} · {self.reunion}'

    @property
    def es_docente(self):
        return self.papel == self.DOCENTE

    @property
    def es_acompanante(self):
        return self.papel == self.ACOMPANANTE


class CambioDeFecha(models.Model):
    """Una reprogramación: lo que había y lo que quedó, con su motivo y quién la hizo."""

    reunion = models.ForeignKey(Reunion, on_delete=models.CASCADE, related_name='cambios_de_fecha')
    fecha_anterior = models.DateField()
    inicio_anterior = models.TimeField()
    fin_anterior = models.TimeField()
    sala_anterior = models.ForeignKey(SalaReunion, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    fecha_nueva = models.DateField()
    inicio_nuevo = models.TimeField()
    fin_nuevo = models.TimeField()
    sala_nueva = models.ForeignKey(SalaReunion, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    motivo = models.TextField('motivo', max_length=1000)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'reprogramación'
        verbose_name_plural = 'reprogramaciones'
        ordering = ['creado', 'pk']
        default_permissions = ()


class ContactoReunion(models.Model):
    """Una confirmación del tutor o un aviso a la familia. Solo se anota: el sistema no envía correos ni mensajes."""

    CONFIRMACION, AVISO = 'CONFIRMACION', 'AVISO'
    TIPOS = [(CONFIRMACION, 'Confirmación del tutor'), (AVISO, 'Aviso a la familia')]
    MEDIOS = [
        ('TELEFONO', 'Llamada telefónica'),
        ('PRESENCIAL', 'En persona'),
        ('MENSAJE', 'Mensaje (WhatsApp o SMS)'),
        ('CORREO', 'Correo electrónico'),
        ('NOTA', 'Nota o recado escrito'),
        ('PORTAL', 'Portal de tutores'),
        ('OTRO', 'Otro'),
    ]

    reunion = models.ForeignKey(Reunion, on_delete=models.CASCADE, related_name='contactos')
    tipo = models.CharField(max_length=14, choices=TIPOS)
    medio = models.CharField('medio', max_length=12, choices=MEDIOS)
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='tutor')
    recibio = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                verbose_name='quién la recibió o avisó')
    momento = models.DateTimeField('cuándo')
    nota = models.CharField('nota', max_length=500, blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'contacto con la familia'
        verbose_name_plural = 'contactos con la familia'
        ordering = ['momento', 'pk']
        default_permissions = ()

    def __str__(self):
        return f'{self.get_tipo_display()} · {self.reunion}'


class EventoReunion(models.Model):
    REGISTRADA, PARTICIPANTES, PROGRAMADA, REPROGRAMADA = 'REGISTRADA', 'PARTICIPANTES', 'PROGRAMADA', 'REPROGRAMADA'
    DISPONIBILIDAD, CONFIRMACION_TUTOR, AVISO, CONFIRMADA = 'DISPONIBILIDAD', 'CONFIRMACION_TUTOR', 'AVISO', 'CONFIRMADA'
    PENDIENTE_CONFIRMAR, SUSTITUTO, INICIADA, REALIZADA = 'PENDIENTE_CONFIRMAR', 'SUSTITUTO', 'INICIADA', 'REALIZADA'
    MINUTA, INASISTENCIA, CANCELADA, ACUERDO, DOCUMENTO, VINCULADA = 'MINUTA', 'INASISTENCIA', 'CANCELADA', 'ACUERDO', 'DOCUMENTO', 'VINCULADA'
    INDICACIONES, ENTERADO, AVANCE_FAMILIA = 'INDICACIONES', 'ENTERADO', 'AVANCE_FAMILIA'
    TIPOS = [
        (REGISTRADA, 'Solicitud registrada'),
        (PARTICIPANTES, 'Participantes'),
        (PROGRAMADA, 'Programada'),
        (REPROGRAMADA, 'Reprogramada'),
        (DISPONIBILIDAD, 'Disponibilidad'),
        (CONFIRMACION_TUTOR, 'Confirmación del tutor'),
        (AVISO, 'Aviso a la familia'),
        (CONFIRMADA, 'Confirmada'),
        (PENDIENTE_CONFIRMAR, 'Vuelve a pendiente de confirmación'),
        (SUSTITUTO, 'Acompañante sustituto'),
        (INICIADA, 'Inició'),
        (REALIZADA, 'Realizada'),
        (MINUTA, 'Minuta'),
        (INASISTENCIA, 'Inasistencia'),
        (CANCELADA, 'Cancelada'),
        (ACUERDO, 'Acuerdos'),
        (DOCUMENTO, 'Documentos'),
        (VINCULADA, 'Reunión vinculada'),
        (INDICACIONES, 'Indicaciones para la familia'),
        (ENTERADO, 'Enterado de la minuta'),
        (AVANCE_FAMILIA, 'Avance de la familia'),
    ]

    reunion = models.ForeignKey(Reunion, on_delete=models.CASCADE, related_name='eventos')
    tipo = models.CharField(max_length=20, choices=TIPOS)
    descripcion = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'evento de una reunión'
        verbose_name_plural = 'bitácora de reuniones'
        ordering = ['creado', 'pk']
        default_permissions = ()

    def __str__(self):
        return f'{self.get_tipo_display()} · {self.reunion}'


# ---------------------------------------------------------------------------
# Minuta, acuerdos y documentos
# ---------------------------------------------------------------------------
class Minuta(models.Model):
    reunion = models.OneToOneField(Reunion, on_delete=models.CASCADE, related_name='minuta')
    inicio_real = models.TimeField('hora real de inicio')
    fin_real = models.TimeField('hora real de término')
    temas = models.TextField('temas tratados', max_length=3000)
    resumen = models.TextField('resumen de la reunión', max_length=5000)
    # Confidencial: nunca aparece en la vista del tutor ni en la minuta para la familia
    notas_internas = models.TextField('notas internas confidenciales', max_length=5000, blank=True)
    siguiente_reunion = models.BooleanField('se necesita otra reunión', default=False)
    siguiente_reunion_nota = models.CharField('para qué', max_length=300, blank=True)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    registrada_en = models.DateTimeField(auto_now_add=True)
    modificada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificada_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'minuta'
        verbose_name_plural = 'minutas'
        default_permissions = ()

    def __str__(self):
        return f'Minuta de {self.reunion}'


class Acuerdo(models.Model):
    PENDIENTE, EN_PROCESO, CUMPLIDO, VENCIDO = 'PENDIENTE', 'EN_PROCESO', 'CUMPLIDO', 'VENCIDO'
    ESTADOS = [(PENDIENTE, 'Pendiente'), (EN_PROCESO, 'En proceso'), (CUMPLIDO, 'Cumplido')]
    NOMBRE_DE_ESTADO = {**dict(ESTADOS), VENCIDO: 'Vencido'}
    QUIENES = [('FAMILIA', 'La familia'), ('ESTUDIANTE', 'El estudiante'), ('ESCUELA', 'El colegio'), ('VARIOS', 'Varios')]

    reunion = models.ForeignKey(Reunion, on_delete=models.CASCADE, related_name='acuerdos')
    descripcion = models.TextField('acuerdo o compromiso', max_length=1000)
    quien = models.CharField('se compromete', max_length=10, choices=QUIENES, default='FAMILIA')
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='acuerdos_de_reuniones',
                                    verbose_name='responsable del seguimiento')
    responsable_texto = models.CharField('responsable (familia o estudiante)', max_length=160, blank=True)
    fecha_limite = models.DateField('fecha límite')
    estado = models.CharField('estado', max_length=10, choices=ESTADOS, default=PENDIENTE)
    compartido = models.BooleanField('compartir con la familia', default=True,
                                     help_text='Aparece en el portal del tutor y en la minuta para la familia.')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    cumplido_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'acuerdo'
        verbose_name_plural = 'acuerdos'
        ordering = ['fecha_limite', 'pk']
        default_permissions = ()

    def __str__(self):
        return f'{self.descripcion[:60]} · {self.fecha_limite:%d/%m/%Y}'

    @property
    def vencido(self):
        return self.estado != self.CUMPLIDO and self.fecha_limite < timezone.localdate()

    @property
    def estado_actual(self):
        """Pendiente, en proceso o cumplido; vencido si pasó su fecha límite sin cumplirse."""
        return self.VENCIDO if self.vencido else self.estado

    @property
    def nombre_estado(self):
        return self.NOMBRE_DE_ESTADO[self.estado_actual]

    @property
    def nombre_responsable(self):
        if self.responsable_id:
            return self.responsable.get_full_name() or self.responsable.get_username()
        return self.responsable_texto or self.get_quien_display()


class SeguimientoAcuerdo(models.Model):
    acuerdo = models.ForeignKey(Acuerdo, on_delete=models.CASCADE, related_name='seguimientos')
    estado = models.CharField('estado', max_length=10, choices=Acuerdo.ESTADOS)
    nota = models.TextField('observaciones del seguimiento', max_length=1000)
    evidencia = models.FileField('evidencia', upload_to=ruta_de_evidencia, max_length=200, blank=True)
    evidencia_nombre = models.CharField(max_length=200, blank=True)
    evidencia_tipo = models.CharField(max_length=80, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    # El avance que reporta la familia desde su portal («Ya lo hice»): lo revisa el responsable (no cambia el estado)
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    revisado_en = models.DateTimeField(null=True, blank=True)
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'seguimiento de un acuerdo'
        verbose_name_plural = 'seguimiento de los acuerdos'
        ordering = ['creado', 'pk']
        default_permissions = ()

    @property
    def de_la_familia(self):
        return self.tutor_id is not None

    @property
    def por_revisar(self):
        return self.de_la_familia and self.revisado_en is None


class AdjuntoReunion(models.Model):
    DOCUMENTO, FIRMA = 'DOCUMENTO', 'FIRMA'
    CLASES = [(DOCUMENTO, 'Documento'), (FIRMA, 'Evidencia de firma de la minuta')]

    reunion = models.ForeignKey(Reunion, on_delete=models.CASCADE, related_name='adjuntos')
    archivo = models.FileField(upload_to=ruta_de_adjunto, max_length=200)
    nombre_original = models.CharField(max_length=200)
    tipo = models.CharField(max_length=80)
    clase = models.CharField('tipo de documento', max_length=10, choices=CLASES, default=DOCUMENTO)
    compartido = models.BooleanField('compartir con la familia', default=False)
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'documento de una reunión'
        verbose_name_plural = 'documentos de las reuniones'
        ordering = ['creado', 'pk']
        default_permissions = ()

    def __str__(self):
        return self.nombre_original

    @property
    def es_imagen(self):
        return self.tipo.startswith('image/')


# ---------------------------------------------------------------------------
# Notificaciones (la campana)
# ---------------------------------------------------------------------------
class NotificacionReunion(models.Model):
    """Un aviso de la campana para una cuenta del personal (`usuario`) o un tutor (`tutor`). Solo dice cuándo y dónde:
    nunca el motivo, la descripción ni las notas. `clave` evita repetir recordatorios y avisos de acuerdos."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    reunion = models.ForeignKey(Reunion, on_delete=models.CASCADE, related_name='notificaciones')
    titulo = models.CharField(max_length=160)
    texto = models.CharField(max_length=300)
    clave = models.CharField(max_length=80, blank=True)
    leida = models.BooleanField(default=False)
    creada = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'notificación de reunión'
        verbose_name_plural = 'notificaciones de reuniones'
        ordering = ['-creada', '-pk']
        default_permissions = ()
        indexes = [
            models.Index(fields=['usuario', 'leida'], name='reunion_notif_usuario'),
            models.Index(fields=['tutor', 'leida'], name='reunion_notif_tutor'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(usuario__isnull=False) | Q(tutor__isnull=False), name='reunion_notif_con_destinatario'),
            models.UniqueConstraint(fields=['usuario', 'clave'], condition=Q(usuario__isnull=False) & ~Q(clave=''),
                                    name='reunion_notif_clave_usuario'),
            models.UniqueConstraint(fields=['tutor', 'clave'], condition=Q(tutor__isnull=False) & ~Q(clave=''),
                                    name='reunion_notif_clave_tutor'),
        ]
