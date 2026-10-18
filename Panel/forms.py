from django import forms

from Alumnos.forms import EstiloCamposMixin

from .models import CriterioSeguimiento

CAMPOS_ASISTENCIA = ('revisar_asistencia', 'faltas_acumuladas', 'faltas_consecutivas', 'inasistencia_maxima', 'dias_minimos')
CAMPOS_RENDIMIENTO = ('revisar_rendimiento', 'calificacion_aprobatoria', 'materias_reprobadas', 'promedio_minimo', 'descenso_minimo')
CAMPOS_PRIORIDAD = ('reprobadas_prioridad_alta',)


class CriterioSeguimientoForm(EstiloCamposMixin, forms.ModelForm):
    """Los criterios de un nivel (un formulario por nivel en la misma página, con su prefijo)."""

    class Meta:
        model = CriterioSeguimiento
        fields = CAMPOS_ASISTENCIA + CAMPOS_RENDIMIENTO + CAMPOS_PRIORIDAD
        widgets = {campo: forms.CheckboxInput(attrs={'class': 'choice__input'}) for campo in ('revisar_asistencia', 'revisar_rendimiento')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def grupos(self):
        """Los campos en sus tres apartados, para la plantilla."""
        return (('Asistencia', [self[c] for c in CAMPOS_ASISTENCIA]), ('Rendimiento', [self[c] for c in CAMPOS_RENDIMIENTO]),
                ('Prioridad', [self[c] for c in CAMPOS_PRIORIDAD]))
