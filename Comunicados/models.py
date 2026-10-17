"""Comunicados (pedido del 2026-10-16): publicaciones informativas del colegio para tutores, estudiantes y profesores,
con su lista de destinatarios y el seguimiento de lectura de cada uno.

Son independientes de la mensajería (Mensajes/): no son conversaciones ni admiten respuesta. Las personas son las del
proyecto (`Alumno`, `Tutor`, `Profesor`): un `Destinatario` apunta a exactamente una de ellas. La lista de
destinatarios queda fija al enviar (las inscripciones posteriores no agregan a nadie) y cada uno guarda su primera
lectura. Quién puede enviar a quién: Comunicados/alcance.py; las operaciones: Comunicados/reglas.py.

Un comunicado eliminado no se borra (`eliminado`): deja de verse para todos y queda en la base y en el historial de
cambios (LogEntry) para su trazabilidad.
"""
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from Alumnos.models import Alumno, Profesor, Tutor


def ruta_de_adjunto(instancia, nombre):
    """Nombre al azar (sin el del archivo original): la dirección no se puede adivinar ni se muestra; los archivos solo
    se entregan por las vistas del módulo, que revisan quién los pide (como las evidencias de Conducta)."""
    extension = Path(nombre).suffix.lower()[:10]
    return f'comunicados/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}{extension}'


class ComunicadoQuerySet(models.QuerySet):
    def visibles(self):
        """Los que no se eliminaron."""
        return self.filter(eliminado=False)

    def activos(self, ahora=None):
        """Los que no han caducado (sin fecha de expiración, o con una todavía por llegar)."""
        ahora = ahora or timezone.now()
        return self.filter(Q(expira__isnull=True) | Q(expira__gt=ahora))

    def caducados(self, ahora=None):
        return self.filter(expira__lte=ahora or timezone.now())


class Comunicado(models.Model):
    MAXIMO_TITULO = 150
    MAXIMO_DESCRIPCION = 5000
    MAXIMO_ADJUNTOS = 5

    titulo = models.CharField('título', max_length=MAXIMO_TITULO)
    descripcion = models.TextField('descripción', max_length=MAXIMO_DESCRIPCION)
    urgente = models.BooleanField(default=False)
    expira = models.DateTimeField('fecha de expiración', null=True, blank=True,
                                  help_text='A partir de esta fecha deja de mostrarse a los destinatarios.')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='comunicados_enviados')
    # El rol de quien lo envió, tal como era al enviarlo («Docente», «Dirección»…): lo muestra «Creado por»
    rol_autor = models.CharField('rol del autor', max_length=80, blank=True)
    creado = models.DateTimeField(default=timezone.now, db_index=True)
    # Lo genera el formulario al abrirse: un doble clic o un reintento del mismo envío no crea un segundo comunicado
    clave_envio = models.UUIDField(unique=True, editable=False)
    eliminado = models.BooleanField(default=False, db_index=True)
    eliminado_en = models.DateTimeField(null=True, blank=True)
    eliminado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    objects = ComunicadoQuerySet.as_manager()

    class Meta:
        verbose_name = 'Comunicado'
        verbose_name_plural = 'Comunicados'
        ordering = ['-creado', '-pk']
        default_permissions = ()
        permissions = [
            ('recibir', 'Consultar los comunicados que recibe (profesores)'),
            ('seguimiento', 'Consultar sus comunicados enviados y quién los ha leído'),
            ('enviar', 'Enviar comunicados a los niveles que tiene asignados'),
            ('eliminar', 'Eliminar sus propios comunicados'),
            ('gestionar', 'Gestionar los comunicados de todo el colegio'),
        ]

    def __str__(self):
        return self.titulo

    def caducado_en(self, ahora=None):
        return self.expira is not None and self.expira <= (ahora or timezone.now())

    @property
    def caducado(self):
        return self.caducado_en()

    @property
    def activo(self):
        return not self.caducado


class Destinatario(models.Model):
    ESTUDIANTE, TUTOR, PROFESOR = 'ESTUDIANTE', 'TUTOR', 'PROFESOR'
    TIPOS = [(TUTOR, 'Tutor'), (ESTUDIANTE, 'Estudiante'), (PROFESOR, 'Profesor')]

    comunicado = models.ForeignKey(Comunicado, on_delete=models.CASCADE, related_name='destinatarios')
    tipo = models.CharField(max_length=10, choices=TIPOS)
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, null=True, blank=True, related_name='comunicados_recibidos')
    tutor = models.ForeignKey(Tutor, on_delete=models.CASCADE, null=True, blank=True, related_name='comunicados_recibidos')
    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE, null=True, blank=True, related_name='comunicados_recibidos')
    # Cómo se le ubicaba al enviarlo («2° A · Primaria», «Tutor de …» con sus estudiantes del alcance de quien envió)
    detalle = models.CharField(max_length=250, blank=True)
    # La primera vez que abrió el comunicado (las siguientes no la cambian)
    leido_en = models.DateTimeField('leído el', null=True, blank=True)

    class Meta:
        verbose_name = 'Destinatario de un comunicado'
        verbose_name_plural = 'Destinatarios de comunicados'
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=(Q(tipo='ESTUDIANTE', alumno__isnull=False, tutor__isnull=True, profesor__isnull=True)
                           | Q(tipo='TUTOR', alumno__isnull=True, tutor__isnull=False, profesor__isnull=True)
                           | Q(tipo='PROFESOR', alumno__isnull=True, tutor__isnull=True, profesor__isnull=False)),
                name='destinatario_una_sola_persona',
            ),
            # Cada persona recibe una sola copia (un tutor con varios hijos, también)
            models.UniqueConstraint(fields=['comunicado', 'alumno'], condition=Q(alumno__isnull=False), name='destinatario_estudiante_unico'),
            models.UniqueConstraint(fields=['comunicado', 'tutor'], condition=Q(tutor__isnull=False), name='destinatario_tutor_unico'),
            models.UniqueConstraint(fields=['comunicado', 'profesor'], condition=Q(profesor__isnull=False), name='destinatario_profesor_unico'),
        ]
        indexes = [models.Index(fields=['comunicado', 'leido_en'], name='destinatario_lectura')]

    def __str__(self):
        return f'{self.persona} · {self.comunicado}'

    @property
    def persona(self):
        return {self.ESTUDIANTE: self.alumno, self.TUTOR: self.tutor, self.PROFESOR: self.profesor}[self.tipo]

    @property
    def nombre(self):
        persona = self.persona
        return persona.nombre_completo if persona else ''

    @property
    def leido(self):
        return self.leido_en is not None


class Adjunto(models.Model):
    comunicado = models.ForeignKey(Comunicado, on_delete=models.CASCADE, related_name='adjuntos')
    archivo = models.FileField(upload_to=ruta_de_adjunto, max_length=200)
    nombre_original = models.CharField(max_length=200)
    tipo = models.CharField(max_length=80)
    tamano = models.PositiveIntegerField(default=0)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Archivo de un comunicado'
        verbose_name_plural = 'Archivos de comunicados'
        default_permissions = ()
        ordering = ['orden', 'pk']

    def __str__(self):
        return self.nombre_original

    @property
    def es_imagen(self):
        return self.tipo.startswith('image/')
