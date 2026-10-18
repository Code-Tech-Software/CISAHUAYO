"""Retiros anticipados (pedido del 2026-10-17): el aviso de un tutor de que recogerá a uno o varios de sus hijos antes de
que termine su horario, y la salida real que confirma el personal del colegio.

- **Motivos** (`MotivoRetiro`): el catálogo que configura el administrador en Ajustes › Retiros. Uno ya usado no se
  borra: se desactiva (deja de ofrecerse, el historial lo conserva).
- **Aviso** (`AvisoRetiro`): lo que registra el tutor, con su folio, la fecha y la hora estimada, el motivo, sus detalles
  (los ve también el tutor) y quién recogerá: el propio tutor u otro tutor del estudiante marcado «Autorizado para
  recoger al estudiante» (TutorAlumno.autorizado_recoger). No se puede autorizar a nadie nuevo desde el aviso.
- **Estudiantes del aviso** (`RetiroEstudiante`): el estado de cada hijo por separado: Avisado, Retirado (el personal
  confirmó su salida tras verificar a quien recoge) o Cancelado. Un hijo puede salir antes que sus hermanos.
- **Bitácora** (`EventoRetiro`): creación, cancelaciones, confirmaciones y correcciones, con quién y cuándo.
- **Observaciones internas** (`NotaInterna`): del personal; el tutor nunca las ve.
- **Notificaciones** (`Notificacion`): los avisos de la campana para el personal y para los tutores.

El retiro es un evento aparte: no cambia la asistencia, la conducta ni las calificaciones. Los permisos están en
`AvisoRetiro.Meta` y se conceden desde «Roles y permisos» (Usuarios/catalogo.py).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from Alumnos.models import Alumno, Inscripcion, Tutor


class MotivoRetiro(models.Model):
    nombre = models.CharField('nombre', max_length=80, unique=True)
    requiere_explicacion = models.BooleanField(
        'requiere explicación', default=False,
        help_text='El tutor debe escribir los detalles del retiro al elegir este motivo.',
    )
    activo = models.BooleanField('activo', default=True, help_text='Solo los activos se ofrecen en los avisos nuevos.')
    orden = models.PositiveSmallIntegerField('orden', default=0, help_text='Los de número menor aparecen primero.')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = 'motivo de retiro'
        verbose_name_plural = 'motivos de retiro'
        ordering = ['orden', 'nombre']
        default_permissions = ()   # se administran con Retiros.configurar


class AvisoRetiro(models.Model):
    folio = models.CharField('folio', max_length=20, unique=True, blank=True, editable=False)
    tutor = models.ForeignKey(Tutor, on_delete=models.PROTECT, related_name='avisos_de_retiro', verbose_name='tutor que avisa')
    fecha = models.DateField('fecha del retiro')
    hora = models.TimeField('hora estimada')
    motivo = models.ForeignKey(MotivoRetiro, on_delete=models.PROTECT, related_name='avisos', verbose_name='motivo')
    detalles = models.TextField('detalles', max_length=1000, blank=True)
    recoge = models.ForeignKey(Tutor, on_delete=models.PROTECT, related_name='retiros_a_su_cargo', verbose_name='quién recoge')
    creado = models.DateTimeField('registrado', auto_now_add=True)

    def __str__(self):
        return self.folio or f'Aviso {self.pk}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.folio:   # el folio sale del número del aviso: RA-2026-00012
            self.folio = f'RA-{self.creado:%Y}-{self.pk:05d}'
            AvisoRetiro.objects.filter(pk=self.pk).update(folio=self.folio)

    class Meta:
        verbose_name = 'aviso de retiro anticipado'
        verbose_name_plural = 'avisos de retiro anticipado'
        ordering = ['-fecha', '-hora', '-pk']
        default_permissions = ()
        permissions = [
            ('consultar', 'Consultar los retiros anticipados de sus niveles y anotar observaciones internas'),
            ('confirmar', 'Confirmar la salida de los estudiantes verificando a quien los recoge'),
            ('corregir', 'Cancelar avisos y corregir salidas ya confirmadas (queda en la bitácora)'),
            ('gestionar', 'Retiros anticipados de todo el colegio'),
            ('configurar', 'Configurar los motivos de retiro'),
        ]


class RetiroEstudiante(models.Model):
    AVISADO, RETIRADO, CANCELADO = 'AVISADO', 'RETIRADO', 'CANCELADO'
    ESTADOS = [(AVISADO, 'Avisado'), (RETIRADO, 'Retirado'), (CANCELADO, 'Cancelado')]

    aviso = models.ForeignKey(AvisoRetiro, on_delete=models.CASCADE, related_name='estudiantes')
    alumno = models.ForeignKey(Alumno, on_delete=models.PROTECT, related_name='retiros', verbose_name='estudiante')
    # Su grupo cuando se avisó (filtros, alcance por nivel y lo que se ve aunque después cambie de grupo)
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.PROTECT, related_name='retiros')
    fecha = models.DateField('fecha del retiro')   # la del aviso: así la base de datos impide dos avisos activos ese día
    estado = models.CharField('estado', max_length=10, choices=ESTADOS, default=AVISADO)

    # Salida real
    salida_en = models.DateTimeField('salió', null=True, blank=True)
    confirmado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='confirmó')
    confirmado_en = models.DateTimeField('confirmado', null=True, blank=True)
    recogio = models.ForeignKey(
        Tutor, null=True, blank=True, on_delete=models.PROTECT, related_name='retiros_recogidos', verbose_name='quién recogió')
    observaciones_salida = models.TextField('observaciones de la salida', max_length=1000, blank=True)

    # Cancelación (por el tutor o por el personal)
    cancelado_en = models.DateTimeField('cancelado', null=True, blank=True)
    cancelado_por_tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cancelado_por_usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    motivo_cancelacion = models.TextField('motivo de la cancelación', max_length=500, blank=True)

    def __str__(self):
        return f'{self.alumno} · {self.aviso}'

    class Meta:
        verbose_name = 'estudiante de un retiro'
        verbose_name_plural = 'estudiantes de los retiros'
        ordering = ['aviso', 'alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre']
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['aviso', 'alumno'], name='retiro_estudiante_unico'),
            models.UniqueConstraint(fields=['alumno', 'fecha'], condition=Q(estado='AVISADO'), name='retiro_activo_por_dia'),
        ]


class EventoRetiro(models.Model):
    CREADO, CANCELADO, CONFIRMADO, CORREGIDO = 'CREADO', 'CANCELADO', 'CONFIRMADO', 'CORREGIDO'
    TIPOS = [(CREADO, 'Aviso registrado'), (CANCELADO, 'Cancelación'), (CONFIRMADO, 'Salida confirmada'), (CORREGIDO, 'Corrección')]

    aviso = models.ForeignKey(AvisoRetiro, on_delete=models.CASCADE, related_name='eventos')
    estudiante = models.ForeignKey(RetiroEstudiante, null=True, blank=True, on_delete=models.CASCADE, related_name='eventos')
    tipo = models.CharField(max_length=12, choices=TIPOS)
    descripcion = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    datos = models.JSONField(default=dict, blank=True)   # en una corrección: lo que había y lo que quedó
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.get_tipo_display()} · {self.aviso}'

    class Meta:
        verbose_name = 'evento de un retiro'
        verbose_name_plural = 'bitácora de retiros'
        ordering = ['creado', 'pk']
        default_permissions = ()


class NotaInterna(models.Model):
    aviso = models.ForeignKey(AvisoRetiro, on_delete=models.CASCADE, related_name='notas')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    texto = models.TextField(max_length=1000)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'observación interna'
        verbose_name_plural = 'observaciones internas'
        ordering = ['creada', 'pk']
        default_permissions = ()


class Notificacion(models.Model):
    """Un aviso de la campana: para una cuenta del personal (`usuario`) o para un tutor (`tutor`)."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    aviso = models.ForeignKey(AvisoRetiro, on_delete=models.CASCADE, related_name='notificaciones')
    titulo = models.CharField(max_length=160)
    texto = models.CharField(max_length=300)
    leida = models.BooleanField(default=False)
    creada = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'notificación de retiro'
        verbose_name_plural = 'notificaciones de retiros'
        ordering = ['-creada', '-pk']
        default_permissions = ()
        indexes = [
            models.Index(fields=['usuario', 'leida'], name='retiro_notif_usuario'),
            models.Index(fields=['tutor', 'leida'], name='retiro_notif_tutor'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(usuario__isnull=False) | Q(tutor__isnull=False), name='retiro_notif_con_destinatario'),
        ]
