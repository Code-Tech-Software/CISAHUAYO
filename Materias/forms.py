import re

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from Alumnos.forms import CicloChoiceField, EstiloCamposMixin
from Alumnos.models import CicloEscolar, Materia
from Alumnos.utils import compactar_espacios

CLAVE_VALIDA = re.compile(r'^[\w.-]+$')


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
class MateriaForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición. La baja y la reactivación son acciones aparte (no hay borrado físico)."""

    class Meta:
        model = Materia
        fields = ['clave', 'nombre']
        widgets = {
            'clave': forms.TextInput(attrs={'placeholder': 'MAT', 'autocapitalize': 'characters', 'autocomplete': 'off', 'spellcheck': 'false'}),
            'nombre': forms.TextInput(attrs={'placeholder': 'Matemáticas', 'autocomplete': 'off', 'autofocus': True}),
        }
        help_texts = {
            'clave': 'Código corto y único: letras, números, punto o guion. Se guarda en mayúsculas.',
            'nombre': 'Cómo aparece en los horarios y en los listados.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_clave(self):
        clave = re.sub(r'\s+', '-', compactar_espacios(self.cleaned_data.get('clave'))).upper()
        if not CLAVE_VALIDA.match(clave):
            raise ValidationError('Usa solo letras, números, punto o guion.')
        if Materia.objects.filter(clave__iexact=clave).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya existe una materia con esa clave.')
        return clave

    def clean_nombre(self):
        return compactar_espacios(self.cleaned_data.get('nombre'))


# ---------------------------------------------------------------------------
# Listado: filtros
# ---------------------------------------------------------------------------
class FiltroMateriasForm(EstiloCamposMixin, forms.Form):
    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Clave o nombre de la materia…', 'autocomplete': 'off',
    }))
    estado = forms.ChoiceField(required=False, choices=[('', 'Activas'), ('BAJA', 'Bajas')], label='Estado')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    @property
    def activos(self):
        """Valores válidos de los filtros (los inválidos de la URL se ignoran)."""
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}

    def filtrar(self, queryset, con_estado=True):
        datos = self.activos
        for palabra in datos.get('q', '').split():
            queryset = queryset.filter(Q(clave__icontains=palabra) | Q(nombre__icontains=palabra))
        if con_estado:
            queryset = queryset.filter(activa=datos.get('estado') != 'BAJA')
        return queryset.order_by('nombre', 'clave')


# ---------------------------------------------------------------------------
# Copiar el plan (materias y horarios) de un ciclo a otro
# ---------------------------------------------------------------------------
class CopiarPlanForm(EstiloCamposMixin, forms.Form):
    origen = CicloChoiceField(CicloEscolar.objects.all(), empty_label='Selecciona el ciclo de origen', label='Copiar de este ciclo')
    destino = CicloChoiceField(CicloEscolar.objects.all(), empty_label='Selecciona el ciclo de destino', label='A este ciclo')
    horarios = forms.BooleanField(required=False, initial=True, label='Copiar también los horarios', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))
    conservar_profesor = forms.BooleanField(
        required=False, initial=True, label='Conservar al profesor de cada materia', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Se copia hacia el ciclo actual o hacia uno próximo, nunca hacia uno cerrado.
        self.fields['destino'].queryset = CicloEscolar.objects.filter(Q(activo=True) | Q(fecha_inicio__gt=timezone.localdate()))
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        origen, destino = datos.get('origen'), datos.get('destino')
        if origen and destino and origen == destino:
            self.add_error('destino', 'El ciclo de destino debe ser distinto al de origen.')
        return datos
