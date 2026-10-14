from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.forms import formset_factory

from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Grado

from . import reglas
from .models import Actividad, ConfiguracionEvaluacion, Rubro

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


def _texto(valor):
    return ' '.join((valor or '').split())


# ---------------------------------------------------------------------------
# Actividades (procedimientos y exámenes)
# ---------------------------------------------------------------------------
class ActividadForm(EstiloCamposMixin, forms.Form):
    nombre = forms.CharField(max_length=120, label='Nombre', widget=forms.TextInput(attrs={'autocomplete': 'off', 'autofocus': True}),
                             error_messages={'required': 'Escribe el nombre.'})
    descripcion = forms.CharField(required=False, max_length=1000, label='Descripción (opcional)', widget=forms.Textarea(attrs={'rows': 2}))
    fecha = forms.DateField(label='Fecha', widget=FECHA, error_messages={'required': 'Indica la fecha.', 'invalid': 'Escribe una fecha válida.'})
    rubro = forms.ModelChoiceField(Rubro.objects.none(), label='Rubro', empty_label=None,
                                   error_messages={'required': 'Elige el rubro.', 'invalid_choice': 'Elige un rubro de la lista.'})
    orden = forms.IntegerField(required=False, min_value=1, max_value=9999, label='Orden', help_text='Posición de la columna (vacío: al final).')

    def __init__(self, *args, acta, tipo, actividad=None, **kwargs):
        if actividad is not None and 'initial' not in kwargs:
            kwargs['initial'] = {'nombre': actividad.nombre, 'descripcion': actividad.descripcion, 'fecha': actividad.fecha,
                                 'rubro': actividad.rubro_id, 'orden': actividad.orden}
        super().__init__(*args, **kwargs)
        self.acta, self.tipo, self.actividad = acta, tipo, actividad
        rubros = reglas.rubros_para_actividades(acta, tipo)
        if actividad is not None and actividad.rubro_id not in {r.pk for r in rubros}:
            rubros.append(actividad.rubro)
        self.fields['rubro'].queryset = Rubro.objects.filter(pk__in=[r.pk for r in rubros]).order_by('orden', 'pk')
        if len(rubros) == 1:
            self.fields['rubro'].initial = rubros[0].pk
        if actividad is None and not self.is_bound:
            hoy = reglas.hoy()
            self.initial.setdefault('fecha', hoy if reglas.fecha_en_periodo(hoy, acta.periodo) else acta.periodo.fecha_inicio)
        self.aplicar_estilo()

    def clean_nombre(self):
        return _texto(self.cleaned_data.get('nombre'))

    def clean_descripcion(self):
        return (self.cleaned_data.get('descripcion') or '').strip()

    def clean_fecha(self):
        fecha = self.cleaned_data.get('fecha')
        periodo = self.acta.periodo
        if fecha and not reglas.fecha_en_periodo(fecha, periodo):
            raise ValidationError(f'La fecha debe estar dentro de {periodo.nombre} (del {periodo.fecha_inicio:%d/%m/%Y} al {periodo.fecha_fin:%d/%m/%Y}).')
        return fecha


class MotivoForm(EstiloCamposMixin, forms.Form):
    motivo = forms.CharField(max_length=1000, label='Motivo', widget=forms.Textarea(attrs={'rows': 3, 'autofocus': True}),
                             error_messages={'required': 'Escribe el motivo.'})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_motivo(self):
        motivo = _texto(self.cleaned_data.get('motivo'))
        if len(motivo) < 5:
            raise ValidationError('Explica el motivo (al menos 5 caracteres).')
        return motivo


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
class ReglasForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = ConfiguracionEvaluacion
        fields = ['penalizar_faltas', 'faltas_por_bloque', 'puntos_por_bloque', 'origen_faltas', 'punto_academia',
                  'valor_punto_academia', 'limite_maximo', 'usar_limite_minimo', 'limite_minimo']
        widgets = {
            'penalizar_faltas': forms.CheckboxInput(attrs={'class': 'choice__input'}),
            'punto_academia': forms.CheckboxInput(attrs={'class': 'choice__input'}),
            'usar_limite_minimo': forms.CheckboxInput(attrs={'class': 'choice__input'}),
            'faltas_por_bloque': forms.NumberInput(attrs={'min': 1, 'step': 1}),
            'puntos_por_bloque': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'valor_punto_academia': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'limite_maximo': forms.NumberInput(attrs={'min': 0, 'max': 10, 'step': '0.01'}),
            'limite_minimo': forms.NumberInput(attrs={'min': 0, 'max': 10, 'step': '0.01'}),
        }
        help_texts = {
            'faltas_por_bloque': 'Se descuenta por cada bloque completo (con 2: 0-1 faltas, nada; 2-3, un descuento; 4-5, dos).',
            'origen_faltas': 'El formato no dice si son justificadas o no: elige cuáles cuentan. Las de la asistencia no se vuelven a capturar.',
            'usar_limite_minimo': 'El formato no tiene calificación mínima (el resultado puede quedar debajo de 0): actívala solo si el colegio lo decide.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        maximo, minimo = datos.get('limite_maximo'), datos.get('limite_minimo')
        if datos.get('usar_limite_minimo') and maximo is not None and minimo is not None and minimo > maximo:
            self.add_error('limite_minimo', 'La mínima no puede ser mayor que la máxima.')
        return datos


class RubroForm(EstiloCamposMixin, forms.Form):
    pk = forms.IntegerField(required=False, widget=forms.HiddenInput)
    nombre = forms.CharField(max_length=80, label='Nombre', widget=forms.TextInput(attrs={'autocomplete': 'off'}),
                             error_messages={'required': 'Escribe el nombre del rubro.'})
    porcentaje = forms.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0'), max_value=Decimal('100'), label='Porcentaje',
                                    widget=forms.NumberInput(attrs={'min': 0, 'max': 100, 'step': '0.01', 'data-porcentaje': ''}),
                                    error_messages={'required': 'Indica el porcentaje.', 'invalid': 'Escribe un número.'})
    tipo = forms.ChoiceField(choices=Rubro.TIPOS, label='Tipo de captura')
    activo = forms.BooleanField(required=False, label='Activo', widget=forms.CheckboxInput(attrs={'class': 'choice__input', 'data-activo': ''}))
    orden = forms.IntegerField(required=False, widget=forms.HiddenInput(attrs={'data-orden': ''}))
    eliminar = forms.BooleanField(required=False, widget=forms.HiddenInput(attrs={'data-eliminar': ''}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_nombre(self):
        return _texto(self.cleaned_data.get('nombre'))

    @property
    def se_elimina(self):
        """Se marcó para quitar (la fila se oculta; al guardar se elimina)."""
        valor = self['eliminar'].value()
        return valor is True or str(valor).lower() in ('1', 'true', 'on')


RubroFormSet = formset_factory(RubroForm, extra=0, max_num=30, validate_max=True)


def rubros_iniciales(configuracion):
    return [{'pk': r.pk, 'nombre': r.nombre, 'porcentaje': r.porcentaje, 'tipo': r.tipo, 'activo': r.activo, 'orden': r.orden}
            for r in configuracion.rubros.all()]


class FiltroConfiguracionForm(EstiloCamposMixin, forms.Form):
    nivel = forms.ChoiceField(required=False, choices=[('', 'Todos los niveles'), *Grado.NIVEL_CHOICES], label='Nivel')
    q = forms.CharField(required=False, max_length=80, label='Buscar materia', widget=forms.TextInput(attrs={'placeholder': 'Buscar materia…', 'type': 'search'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    @property
    def activos(self):
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}


class NuevaVersionForm(EstiloCamposMixin, forms.Form):
    periodo = forms.ModelChoiceField(queryset=None, label='Periodo', empty_label='Elige el periodo',
                                     error_messages={'required': 'Elige el periodo.', 'invalid_choice': 'Elige un periodo de la lista.'})

    def __init__(self, *args, periodos, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['periodo'].queryset = periodos
        self.aplicar_estilo()


TIPOS_DE_ACTIVIDAD = {'procedimientos': Actividad.PROCEDIMIENTO, 'examenes': Actividad.EXAMEN}
