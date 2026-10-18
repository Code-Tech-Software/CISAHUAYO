"""Panel de control (pedido del 2026-10-18): los criterios con que el panel señala a los «Estudiantes que requieren
atención».

El sistema no tenía umbrales para estas alertas ni una calificación aprobatoria configurada (el portal solo pinta en
rojo las calificaciones menores que 6), así que aquí se configuran por nivel. Mientras un nivel no se guarde, se usan
los valores iniciales propuestos de `PROPUESTOS` (no son reglas institucionales: el colegio debe revisarlos). Las
alertas son preventivas, para dar seguimiento: no generan sanciones ni cambian calificaciones.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from Alumnos.models import Grado

# Valores iniciales propuestos (se explican en la página de Ajustes)
PROPUESTOS = {
    'faltas_acumuladas': 5,                       # faltas sin justificar en el periodo
    'faltas_consecutivas': 3,                     # días de clases seguidos con falta sin justificar
    'inasistencia_maxima': Decimal('10.00'),      # % de días con falta (justificada o no) sobre los días con registro
    'dias_minimos': 10,                           # días con registro para calcular el porcentaje
    'calificacion_aprobatoria': Decimal('6.00'),  # una materia con final menor está reprobada
    'materias_reprobadas': 1,
    'promedio_minimo': Decimal('7.00'),
    'descenso_minimo': Decimal('1.00'),           # puntos de baja entre dos periodos comparables
    'reprobadas_prioridad_alta': 3,
}


class CriterioSeguimiento(models.Model):
    nivel = models.CharField('nivel', max_length=20, choices=Grado.NIVEL_CHOICES, unique=True)

    # Asistencia (la de entrada al colegio, en el periodo de evaluación del nivel)
    revisar_asistencia = models.BooleanField('revisar la asistencia', default=True)
    faltas_acumuladas = models.PositiveSmallIntegerField(
        'faltas sin justificar', default=PROPUESTOS['faltas_acumuladas'], validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Alerta cuando el estudiante acumula esta cantidad o más de faltas sin justificar en el periodo.')
    faltas_consecutivas = models.PositiveSmallIntegerField(
        'faltas seguidas', default=PROPUESTOS['faltas_consecutivas'], validators=[MinValueValidator(2), MaxValueValidator(30)],
        help_text='Días de clases seguidos con falta sin justificar.')
    inasistencia_maxima = models.DecimalField(
        'inasistencia máxima (%)', max_digits=5, decimal_places=2, default=PROPUESTOS['inasistencia_maxima'],
        validators=[MinValueValidator(Decimal('1')), MaxValueValidator(Decimal('100'))],
        help_text='Porcentaje de días con falta (justificada o no) sobre los días con registro; si lo supera, hay alerta.')
    dias_minimos = models.PositiveSmallIntegerField(
        'días con registro mínimos', default=PROPUESTOS['dias_minimos'], validators=[MinValueValidator(1), MaxValueValidator(200)],
        help_text='El porcentaje solo se calcula con al menos estos días con registro (con menos no es representativo).')

    # Rendimiento (calificaciones finales de las actas cerradas)
    revisar_rendimiento = models.BooleanField('revisar el rendimiento', default=True)
    calificacion_aprobatoria = models.DecimalField(
        'calificación aprobatoria', max_digits=4, decimal_places=2, default=PROPUESTOS['calificacion_aprobatoria'],
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('10'))],
        help_text='Una materia con calificación final menor que esta se cuenta como reprobada.')
    materias_reprobadas = models.PositiveSmallIntegerField(
        'materias reprobadas', default=PROPUESTOS['materias_reprobadas'], validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text='Alerta cuando el estudiante reprueba esta cantidad o más de materias en el periodo.')
    promedio_minimo = models.DecimalField(
        'promedio mínimo', max_digits=4, decimal_places=2, default=PROPUESTOS['promedio_minimo'],
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('10'))],
        help_text='Alerta cuando el promedio del periodo es menor que este.')
    descenso_minimo = models.DecimalField(
        'descenso (puntos)', max_digits=4, decimal_places=2, default=PROPUESTOS['descenso_minimo'],
        validators=[MinValueValidator(Decimal('0.1')), MaxValueValidator(Decimal('10'))],
        help_text='Alerta cuando el promedio baja esta cantidad o más respecto del periodo anterior, en las mismas materias.')

    # Prioridad
    reprobadas_prioridad_alta = models.PositiveSmallIntegerField(
        'reprobadas para prioridad alta', default=PROPUESTOS['reprobadas_prioridad_alta'], validators=[MinValueValidator(1), MaxValueValidator(30)],
        help_text='Con esta cantidad o más de materias reprobadas, la prioridad es alta.')

    modificado = models.DateTimeField(auto_now=True)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'criterios de seguimiento'
        verbose_name_plural = 'criterios de seguimiento'
        default_permissions = ('view', 'change')

    def __str__(self):
        return f'Criterios de seguimiento de {self.get_nivel_display()}'

    @classmethod
    def de(cls, nivel):
        """Los del nivel; si todavía no se guardan, los propuestos (sin guardar: `pk` es None)."""
        return cls.objects.filter(nivel=nivel).first() or cls(nivel=nivel)

    @classmethod
    def por_nivel(cls):
        guardados = {c.nivel: c for c in cls.objects.all()}
        return {nivel: guardados.get(nivel) or cls(nivel=nivel) for nivel, _ in Grado.NIVEL_CHOICES}

    @property
    def es_propuesto(self):
        return self.pk is None
