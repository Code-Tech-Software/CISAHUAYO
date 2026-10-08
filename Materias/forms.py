import re

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from Alumnos.forms import CicloChoiceField, EstiloCamposMixin
from Alumnos.models import CicloEscolar, Grado, Materia, MateriaGrado
from Alumnos.utils import compactar_espacios

from .claves import clave_sugerida

CLAVE_VALIDA = re.compile(r'^[\w.-]+$')


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
class MateriaForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición. La baja y la reactivación son acciones aparte (no hay borrado físico).

    Al registrarla se eligen los grados en los que se imparte: se agrega a su plan del ciclo actual (si lo hay y quien
    registra puede modificar el plan). La clave se propone con las iniciales y el grado («MAT-1P») y se puede cambiar; si
    se deja vacía, se usa la propuesta.
    """

    grados = forms.ModelMultipleChoiceField(
        queryset=Grado.objects.none(), required=False, label='Grados en los que se imparte',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        error_messages={'required': 'Elige al menos un grado.'},
    )

    class Meta:
        model = Materia
        fields = ['clave', 'nombre']
        widgets = {
            'clave': forms.TextInput(attrs={'placeholder': 'MAT-1P', 'autocapitalize': 'characters', 'autocomplete': 'off', 'spellcheck': 'false'}),
            'nombre': forms.TextInput(attrs={'placeholder': 'Matemáticas', 'autocomplete': 'off', 'autofocus': True}),
        }
        help_texts = {
            'clave': 'Código corto y único: letras, números, punto o guion. Se guarda en mayúsculas.',
            'nombre': 'Cómo aparece en los horarios y en los listados.',
        }

    def __init__(self, *args, ciclo=None, puede_asignar=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = self.instance._state.adding
        self.ciclo = ciclo
        self.grados_asignados = []
        # Los grados se piden al registrarla, si hay un ciclo actual al que agregarla, grados y permiso para modificar su plan
        self.motivo_sin_grados = ''
        if self.creando:
            if ciclo is None:
                self.motivo_sin_grados = 'No hay un ciclo escolar actual'
            elif not puede_asignar:
                self.motivo_sin_grados = 'No tienes permiso para modificar el plan de materias'
            elif not Grado.objects.filter(activo=True).exists():
                self.motivo_sin_grados = 'Todavía no hay grados activos'
        if self.creando and not self.motivo_sin_grados:
            self.fields['grados'].queryset = Grado.objects.filter(activo=True).academicos()
            self.fields['grados'].required = True
            self.fields['grados'].help_text = f'Se agrega a su plan del ciclo {ciclo}. Después puedes agregarla a más grados desde su perfil.'
        else:
            del self.fields['grados']
        if self.creando:
            self.fields['clave'].required = False
            self.fields['clave'].help_text = (
                'Se propone con sus iniciales y el grado (P primaria, S secundaria, K preescolar, B preparatoria); puedes '
                'cambiarla. Debe ser única: letras, números, punto o guion.'
            )
        # materia-form.js pide la propuesta al servidor mientras se escribe el nombre y se eligen los grados
        self.fields['clave'].widget.attrs.update({'data-clave-url': reverse('materias:clave'), 'data-excluir': self.instance.pk or ''})
        self.aplicar_estilo()

    @property
    def grados_por_nivel(self):
        """Las casillas de los grados agrupadas por nivel: [{'nombre': 'Primaria', 'casillas': [...]}, ...]."""
        if 'grados' not in self.fields:
            return []
        niveles = dict(self.fields['grados'].queryset.values_list('pk', 'nivel'))
        nombres = dict(Grado.NIVEL_CHOICES)
        grupos = []
        for casilla in self['grados']:
            nombre = nombres[niveles[int(str(casilla.data['value']))]]
            if not grupos or grupos[-1]['nombre'] != nombre:
                grupos.append({'nombre': nombre, 'casillas': []})
            grupos[-1]['casillas'].append(casilla)
        return grupos

    def clean_clave(self):
        clave = re.sub(r'\s+', '-', compactar_espacios(self.cleaned_data.get('clave'))).upper()
        if not clave and self.creando:
            return ''   # se usa la propuesta (en clean, cuando ya se conocen el nombre y los grados)
        if not CLAVE_VALIDA.match(clave):
            raise ValidationError('Usa solo letras, números, punto o guion.')
        if Materia.objects.filter(clave__iexact=clave).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya existe una materia con esa clave.')
        return clave

    def clean_nombre(self):
        return compactar_espacios(self.cleaned_data.get('nombre'))

    def clean(self):
        datos = super().clean()
        if self.creando and not datos.get('clave') and 'clave' not in self.errors and datos.get('nombre'):
            datos['clave'] = clave_sugerida(datos['nombre'], datos.get('grados') or ())
            if not datos['clave']:
                self.add_error('clave', 'Escribe la clave de la materia.')
        return datos

    def save(self, commit=True):
        materia = super().save(commit)
        grados = list(self.cleaned_data.get('grados') or [])
        if commit and grados and self.ciclo is not None:
            MateriaGrado.objects.bulk_create([MateriaGrado(ciclo=self.ciclo, grado=grado, materia=materia) for grado in grados])
            self.grados_asignados = grados
        return materia


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
