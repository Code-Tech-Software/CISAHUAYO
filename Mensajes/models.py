"""Mensajería interna (pedido del 2026-10-14): conversaciones individuales entre estudiantes, tutores y usuarios del
sistema (docentes y personal), en tiempo real.

Las tres clases de cuenta siguen separadas: un `Participante` envuelve exactamente una (un usuario del sistema, un
`Alumno` o un `Tutor`) y es lo único que la mensajería conoce. Las conversaciones y los mensajes se guardan aquí, en
la base de datos del proyecto (sobreviven a cualquier reinicio); Redis solo reparte los avisos en tiempo real
(Mensajes/tiempo_real.py). Quién puede escribirle a quién: Mensajes/reglas.py.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from Alumnos.models import Alumno, Tutor


class Participante(models.Model):
    SISTEMA, ESTUDIANTE, TUTOR = 'SISTEMA', 'ESTUDIANTE', 'TUTOR'
    TIPOS = [(SISTEMA, 'Usuario del sistema'), (ESTUDIANTE, 'Estudiante'), (TUTOR, 'Tutor')]

    tipo = models.CharField(max_length=10, choices=TIPOS)
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='participante_mensajes')
    alumno = models.OneToOneField(Alumno, on_delete=models.CASCADE, null=True, blank=True, related_name='participante_mensajes')
    tutor = models.OneToOneField(Tutor, on_delete=models.CASCADE, null=True, blank=True, related_name='participante_mensajes')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Participante de la mensajería'
        verbose_name_plural = 'Participantes de la mensajería'
        default_permissions = ()
        permissions = [
            ('usar', 'Usar la mensajería con otros usuarios del sistema (y un docente, con sus estudiantes y sus tutores)'),
            ('contactar_familias', 'Escribir a estudiantes y tutores y atender sus mensajes'),
        ]
        constraints = [
            # Exactamente una cuenta, la de su tipo
            models.CheckConstraint(
                condition=(Q(tipo='SISTEMA', usuario__isnull=False, alumno__isnull=True, tutor__isnull=True)
                           | Q(tipo='ESTUDIANTE', usuario__isnull=True, alumno__isnull=False, tutor__isnull=True)
                           | Q(tipo='TUTOR', usuario__isnull=True, alumno__isnull=True, tutor__isnull=False)),
                name='participante_una_sola_cuenta',
            ),
        ]

    def __str__(self):
        return self.nombre

    @property
    def cuenta(self):
        return self.usuario if self.tipo == self.SISTEMA else (self.alumno if self.tipo == self.ESTUDIANTE else self.tutor)

    @property
    def nombre(self):
        if self.tipo == self.SISTEMA:
            return self.usuario.get_full_name() or self.usuario.get_username()
        return self.cuenta.nombre_completo

    @property
    def iniciales(self):
        if self.tipo == self.SISTEMA:
            partes = [p for p in (self.usuario.first_name, self.usuario.last_name) if p] or [self.usuario.get_username()]
            return ''.join(p[0] for p in partes)[:2].upper()
        return self.cuenta.iniciales

    @property
    def clave(self):
        """Cómo se identifica la cuenta fuera de la base («u:7», «a:12», «t:3»), en búsquedas y formularios."""
        return {self.SISTEMA: f'u:{self.usuario_id}', self.ESTUDIANTE: f'a:{self.alumno_id}', self.TUTOR: f't:{self.tutor_id}'}[self.tipo]


class Conversacion(models.Model):
    """Una conversación individual entre dos participantes (`clave`: sus ids ordenados, para que sea una sola)."""

    clave = models.CharField(max_length=40, unique=True)
    participantes = models.ManyToManyField(Participante, through='Miembro', related_name='conversaciones')
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now_add=True, db_index=True)   # la del último mensaje: ordena la bandeja
    ultimo_mensaje = models.ForeignKey('Mensaje', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'
        default_permissions = ()
        ordering = ['-actualizada']

    def __str__(self):
        return f'Conversación {self.clave}'

    @staticmethod
    def clave_de(*participantes):
        return '-'.join(str(pk) for pk in sorted(p.pk for p in participantes))


class Miembro(models.Model):
    """Un participante en una conversación, con hasta dónde leyó (el id del último mensaje leído)."""

    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='miembros')
    participante = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name='membresias')
    ultimo_leido = models.PositiveBigIntegerField(default=0)
    leido_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Miembro de una conversación'
        verbose_name_plural = 'Miembros de conversaciones'
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['conversacion', 'participante'], name='miembro_unico')]

    def __str__(self):
        return f'{self.participante} en {self.conversacion}'


class Mensaje(models.Model):
    MAXIMO = 2000

    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='mensajes')
    autor = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name='mensajes_enviados')
    texto = models.TextField(max_length=MAXIMO)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Mensaje'
        verbose_name_plural = 'Mensajes'
        default_permissions = ()
        ordering = ['pk']
        indexes = [models.Index(fields=['conversacion', 'id'], name='mensaje_conversacion_id')]

    def __str__(self):
        return f'{self.autor}: {self.texto[:40]}'
