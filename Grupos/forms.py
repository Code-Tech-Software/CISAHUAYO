from django import forms
from django.core.exceptions import ValidationError

from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import NombreGrupo
from Alumnos.utils import compactar_espacios


class NombreGrupoForm(EstiloCamposMixin, forms.ModelForm):
    """Un nombre del catálogo de grupos («A», «B», «Matutino»). Renombrarlo renombra los grupos que lo usan."""

    class Meta:
        model = NombreGrupo
        fields = ['nombre', 'orden']
        widgets = {
            'nombre': forms.TextInput(attrs={'placeholder': 'A', 'autocomplete': 'off', 'autofocus': True}),
            'orden': forms.NumberInput(attrs={'min': 0, 'inputmode': 'numeric'}),
        }
        labels = {'orden': 'Orden'}
        help_texts = {
            'nombre': 'Una letra («A», «B») o una palabra corta («Matutino»). Así se verá: «1.º A Primaria».',
            'orden': 'En qué lugar aparece al listar los grupos de un grado (el más bajo, primero).',
        }
        error_messages = {'nombre': {'required': 'Escribe el nombre del grupo.'}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance._state.adding and not self.is_bound:
            ultimo = NombreGrupo.objects.order_by('-orden').values_list('orden', flat=True).first()
            self.initial['orden'] = (ultimo or 0) + 1
        self.aplicar_estilo()

    def clean_nombre(self):
        nombre = compactar_espacios(self.cleaned_data.get('nombre'))
        if len(nombre) <= 2:
            nombre = nombre.upper()   # «a» → «A»
        if NombreGrupo.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya existe un grupo con ese nombre.')
        return nombre
