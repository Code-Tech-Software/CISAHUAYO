from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from Alumnos.academico import activar_ciclo, sugerir_ciclo
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import CicloEscolar
from Alumnos.utils import compactar_espacios


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
class CicloForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = CicloEscolar
        fields = ['nombre', 'fecha_inicio', 'fecha_fin', 'activo']
        labels = {'activo': 'Es el ciclo actual'}
        widgets = {
            'nombre': forms.TextInput(attrs={'placeholder': '2026-2027', 'autocomplete': 'off', 'autofocus': True}),
            'fecha_inicio': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'fecha_fin': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'activo': forms.CheckboxInput(attrs={'class': 'choice__input'}),
        }
        help_texts = {
            'nombre': 'Normalmente el año en que empieza y el año en que termina, por ejemplo 2026-2027.',
            'activo': 'Solo hay un ciclo actual: al marcarlo, el que lo era deja de serlo. En el ciclo actual se inscribe y se toma asistencia.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = self.instance._state.adding
        if self.creando and not self.is_bound:
            # Propone el ciclo que sigue al más reciente; será el actual si todavía no hay uno.
            self.initial.update(sugerir_ciclo())
            self.initial['activo'] = not CicloEscolar.objects.filter(activo=True).exists()
        self.aplicar_estilo()

    def clean_nombre(self):
        nombre = compactar_espacios(self.cleaned_data.get('nombre'))
        if CicloEscolar.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya existe un ciclo con ese nombre.')
        return nombre

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get('fecha_inicio'), datos.get('fecha_fin')
        # El orden de las fechas lo valida el modelo; aquí, que no se empalmen con otro ciclo.
        if inicio and fin and inicio < fin:
            otro = (
                CicloEscolar.objects.filter(fecha_inicio__lte=fin, fecha_fin__gte=inicio)
                .exclude(pk=self.instance.pk).order_by('fecha_inicio').first()
            )
            if otro:
                self.add_error('fecha_inicio', (
                    f'Las fechas se empalman con el ciclo {otro.nombre} '
                    f'({otro.fecha_inicio:%d/%m/%Y} al {otro.fecha_fin:%d/%m/%Y}).'
                ))
        return datos

    def save(self, commit=True):
        with transaction.atomic():
            ciclo = super().save(commit)
            if commit and ciclo.activo:
                activar_ciclo(ciclo)  # el que era actual deja de serlo
        return ciclo


# ---------------------------------------------------------------------------
# Listado: filtro por estado
# ---------------------------------------------------------------------------
class FiltroCiclosForm(forms.Form):
    ESTADOS = ('ACTUAL', 'PROXIMO', 'CERRADO')

    estado = forms.ChoiceField(required=False, choices=[('', 'Todos'), *[(e, e) for e in ESTADOS]])

    @property
    def activos(self):
        """Valores válidos de los filtros (los inválidos de la URL se ignoran)."""
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}

    def filtrar(self, queryset):
        hoy = timezone.localdate()
        estado = self.activos.get('estado')
        if estado == 'ACTUAL':
            queryset = queryset.filter(activo=True)
        elif estado == 'PROXIMO':
            queryset = queryset.filter(activo=False, fecha_inicio__gt=hoy)
        elif estado == 'CERRADO':
            queryset = queryset.filter(activo=False, fecha_inicio__lte=hoy)
        return queryset.order_by('-fecha_inicio')
