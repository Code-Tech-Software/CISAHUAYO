from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from Alumnos.academico import ciclo_actual, motivo_no_inscribible
from Alumnos.forms import CicloChoiceField, EstiloCamposMixin, GradoChoiceField, grados_disponibles
from Alumnos.models import Alumno, CicloEscolar, Grado, Inscripcion, orden_de_nivel

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
class InscripcionForm(EstiloCamposMixin, forms.ModelForm):
    """Inscribe a un alumno en un ciclo y grado. Al editar solo cambian el grado y la fecha."""

    alumno = forms.ModelChoiceField(
        Alumno.objects.all(),
        widget=forms.HiddenInput,
        error_messages={'required': 'Busca y elige un alumno.', 'invalid_choice': 'Elige un alumno de la lista.'},
    )

    class Meta:
        model = Inscripcion
        fields = ['alumno', 'ciclo', 'grado', 'fecha_inscripcion']
        field_classes = {'ciclo': CicloChoiceField, 'grado': GradoChoiceField}
        widgets = {'fecha_inscripcion': FECHA}
        help_texts = {
            'ciclo': 'Se puede inscribir en el ciclo actual o en uno próximo.',
            'grado': 'Solo hay un grupo por grado.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = self.instance._state.adding
        self.existente = None  # inscripción previa del mismo alumno en el mismo ciclo, si la hay

        self.fields['ciclo'].empty_label = 'Selecciona un ciclo'
        self.fields['grado'].empty_label = 'Selecciona un grado'
        if self.creando:
            self.fields['grado'].queryset = grados_disponibles()
            if not self.is_bound:
                self.initial.setdefault('ciclo', ciclo_actual())
        else:
            # El alumno y el ciclo no cambian: otro alumno u otro ciclo sería otra inscripción.
            del self.fields['alumno'], self.fields['ciclo']
            self.fields['grado'].queryset = grados_disponibles(incluir=self.instance.grado)
        self.aplicar_estilo()

    def clean_fecha_inscripcion(self):
        fecha = self.cleaned_data['fecha_inscripcion']
        if fecha > timezone.localdate():
            raise ValidationError('La fecha de inscripción no puede ser futura.')
        return fecha

    def clean(self):
        datos = super().clean()
        if not self.creando:
            return datos

        alumno, ciclo = datos.get('alumno'), datos.get('ciclo')
        if alumno:
            motivo = motivo_no_inscribible(alumno)
            if motivo:
                self.add_error('alumno', motivo)
        if alumno and ciclo and 'alumno' not in self.errors:
            self.existente = Inscripcion.objects.filter(alumno=alumno, ciclo=ciclo).select_related('grado').first()
            if self.existente and self.existente.activa:
                self.add_error('ciclo', f'{alumno} ya está inscrito en el ciclo {ciclo} ({self.existente.grado}).')
            elif self.existente:
                self.add_error('ciclo', (
                    f'{alumno} ya tuvo una inscripción en el ciclo {ciclo} y se dio de baja. '
                    'Reactívala desde el filtro «Bajas» en lugar de crear otra.'
                ))
        return datos


# ---------------------------------------------------------------------------
# Listado: filtros
# ---------------------------------------------------------------------------
class FiltroInscripcionesForm(EstiloCamposMixin, forms.Form):
    ORDEN_ALUMNO = ('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')
    ORDEN_CHOICES = [
        ('alumno', 'Alumno (A-Z)'),
        ('-alumno', 'Alumno (Z-A)'),
        ('grado', 'Grado'),
        ('-reciente', 'Inscripción más reciente'),
        ('antigua', 'Inscripción más antigua'),
    ]

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre, referencia o CURP del alumno…', 'autocomplete': 'off',
    }))
    ciclo = CicloChoiceField(CicloEscolar.objects.all(), required=False, empty_label='Todos los ciclos', label='Ciclo escolar')
    grado = GradoChoiceField(Grado.objects.academicos(), required=False, empty_label='Todos los grados', label='Grado')
    estado = forms.ChoiceField(required=False, choices=[('', 'Activas'), ('BAJA', 'Bajas')], label='Estado')
    orden = forms.ChoiceField(required=False, choices=ORDEN_CHOICES, label='Ordenar por')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    @property
    def activos(self):
        """Valores válidos de los filtros (los inválidos de la URL se ignoran)."""
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}

    def ordenes(self):
        return {
            'alumno': self.ORDEN_ALUMNO,
            '-alumno': tuple(f'-{campo}' for campo in self.ORDEN_ALUMNO),
            'grado': (orden_de_nivel('grado__nivel'), 'grado__numero', *self.ORDEN_ALUMNO),
            '-reciente': ('-fecha_inscripcion', '-pk'),
            'antigua': ('fecha_inscripcion', 'pk'),
        }

    def filtrar(self, queryset, con_estado=True):
        datos = self.activos

        for palabra in datos.get('q', '').split():
            queryset = queryset.filter(
                Q(alumno__nombre__icontains=palabra)
                | Q(alumno__apellido_paterno__icontains=palabra)
                | Q(alumno__apellido_materno__icontains=palabra)
                | Q(alumno__referencia__icontains=palabra)
                | Q(alumno__curp__icontains=palabra)
            )
        if datos.get('ciclo'):
            queryset = queryset.filter(ciclo=datos['ciclo'])
        if datos.get('grado'):
            queryset = queryset.filter(grado=datos['grado'])
        if con_estado:
            queryset = queryset.filter(activa=datos.get('estado') != 'BAJA')
        return queryset.order_by(*self.ordenes()[datos.get('orden', 'alumno')])


# ---------------------------------------------------------------------------
# Reinscripción en bloque (de un ciclo al siguiente)
# ---------------------------------------------------------------------------
class PromocionForm(EstiloCamposMixin, forms.Form):
    origen = CicloChoiceField(CicloEscolar.objects.all(), empty_label='Selecciona el ciclo de origen', label='De este ciclo')
    destino = CicloChoiceField(CicloEscolar.objects.all(), empty_label='Selecciona el ciclo de destino', label='A este ciclo')
    fecha = forms.DateField(required=False, label='Fecha de inscripción', widget=FECHA, initial=timezone.localdate)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Se reinscribe hacia el ciclo actual o hacia uno próximo, nunca hacia uno cerrado.
        self.fields['destino'].queryset = CicloEscolar.objects.filter(
            Q(activo=True) | Q(fecha_inicio__gt=timezone.localdate())
        )
        self.aplicar_estilo()

    def clean_fecha(self):
        fecha = self.cleaned_data.get('fecha') or timezone.localdate()
        if fecha > timezone.localdate():
            raise ValidationError('La fecha de inscripción no puede ser futura.')
        return fecha

    def clean(self):
        datos = super().clean()
        origen, destino = datos.get('origen'), datos.get('destino')
        if origen and destino and origen == destino:
            self.add_error('destino', 'El ciclo de destino debe ser distinto al de origen.')
        return datos
