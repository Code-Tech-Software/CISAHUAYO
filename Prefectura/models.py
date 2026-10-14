"""Prefectura: el alcance de cada cuenta de prefectura y los registros de acceso al colegio (pedido del 2026-10-13).

- **Alcance** (`AlcancePrefectura`): los niveles completos y/o los grupos que una cuenta con un rol de prefectura
  (`Rol.es_prefectura`) puede consultar. Todo el colegio se concede expresamente (`todo_el_colegio`); sin alcance no ve
  a ningún estudiante. Lo aplican las consultas, acciones, reportes, exportaciones y archivos (Prefectura/alcance.py).
- **Accesos** (`MovimientoAcceso`): retardos de ingreso, entradas posteriores y salidas anticipadas, con fecha, hora,
  motivo y quién los registró. Un retardo de ingreso cuenta como la entrada con retardo (asistencia general en retardo
  y falta en la primera clase); lo demás no cambia la asistencia, y el pase de lista del docente nunca se toca. Se
  corrigen con motivo y se anulan (nunca se borran); cada cambio queda en `CambioAcceso`.

Los permisos de prefectura (consultar, registrar, corregir, justificar, solicitar suspensiones, dar seguimiento y
exportar) se declaran aquí y se conceden desde «Roles y permisos» (Usuarios/catalogo.py).
"""
from django.conf import settings
from django.db import models

from Alumnos.models import Alumno, Grado, Grupo, Inscripcion

NIVELES = Grado.NIVEL_CHOICES


class AlcancePrefectura(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='alcance_prefectura')
    todo_el_colegio = models.BooleanField(
        default=False, verbose_name='Todo el colegio',
        help_text='Concede acceso a los estudiantes de todos los niveles y grupos.',
    )
    niveles = models.JSONField(default=list, blank=True, verbose_name='Niveles completos')   # claves de NIVELES
    grupos = models.ManyToManyField(Grupo, blank=True, related_name='+', verbose_name='Grupos')
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Alcance de prefectura'
        verbose_name_plural = 'Alcances de prefectura'
        default_permissions = ()   # lo define quien administra usuarios (auth.change_user)
        permissions = [
            ('consultar', 'Consultar estudiantes, asistencia, conducta y seguimiento (prefectura)'),
            ('registrar', 'Registrar conducta y accesos (prefectura)'),
            ('corregir', 'Corregir y anular sus propios registros abiertos (prefectura)'),
            ('corregir_otros', 'Corregir registros de otros usuarios y casos cerrados (prefectura)'),
            ('justificar', 'Justificar faltas y retardos, y revocar justificaciones (prefectura)'),
            ('solicitar_suspension', 'Solicitar suspensiones y medidas que requieren aprobación (prefectura)'),
            ('dar_seguimiento', 'Dar seguimiento a los casos: citas, acuerdos, compromisos y cierre (prefectura)'),
            ('exportar', 'Imprimir y exportar reportes a PDF y Excel (prefectura)'),
        ]

    def __str__(self):
        return f'Alcance de {self.usuario}'


class MovimientoAcceso(models.Model):
    RETARDO, ENTRADA, SALIDA = 'RETARDO', 'ENTRADA', 'SALIDA'
    TIPOS = [
        (RETARDO, 'Retardo de ingreso'),
        (ENTRADA, 'Entrada posterior'),
        (SALIDA, 'Salida anticipada'),
    ]

    alumno = models.ForeignKey(Alumno, on_delete=models.PROTECT, related_name='accesos', verbose_name='Estudiante')
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.PROTECT, related_name='accesos', verbose_name='Inscripción')
    fecha = models.DateField(verbose_name='Fecha')
    hora = models.TimeField(verbose_name='Hora')
    tipo = models.CharField(max_length=10, choices=TIPOS, verbose_name='Tipo')
    motivo = models.TextField(verbose_name='Motivo')
    acompanante = models.CharField(max_length=160, blank=True, verbose_name='Quién lo acompaña o lo recoge')

    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Registró')
    creado = models.DateTimeField(auto_now_add=True, verbose_name='Registrado el')
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)
    anulado = models.BooleanField(default=False, verbose_name='Anulado')
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True, verbose_name='Motivo de la anulación')

    class Meta:
        verbose_name = 'Registro de acceso'
        verbose_name_plural = 'Registros de acceso'
        ordering = ['-fecha', '-hora', '-pk']
        default_permissions = ()   # se usan los permisos de prefectura
        indexes = [models.Index(fields=['fecha']), models.Index(fields=['alumno', 'fecha'])]

    def __str__(self):
        return f'{self.alumno} · {self.get_tipo_display()} · {self.fecha:%d/%m/%Y} {self.hora:%H:%M}'


class CambioAcceso(models.Model):
    """Bitácora de un registro de acceso: quién lo registró, corrigió o anuló, cuándo, por qué y qué cambió."""

    CREADO, CORREGIDO, ANULADO = 'CREADO', 'CORREGIDO', 'ANULADO'
    ACCIONES = [(CREADO, 'Registró'), (CORREGIDO, 'Corrigió'), (ANULADO, 'Anuló')]

    movimiento = models.ForeignKey(MovimientoAcceso, on_delete=models.CASCADE, related_name='cambios')
    accion = models.CharField(max_length=10, choices=ACCIONES)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    fecha = models.DateTimeField(auto_now_add=True)
    motivo = models.TextField(blank=True)
    cambios = models.JSONField(default=list, blank=True)   # [[qué, antes, después], …]

    class Meta:
        verbose_name = 'Cambio en un registro de acceso'
        verbose_name_plural = 'Cambios en registros de acceso'
        ordering = ['-fecha', '-pk']
        default_permissions = ()
