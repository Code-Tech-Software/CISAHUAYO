"""Formularios de la mensajería: la búsqueda de la moderación (Mensajes/views_moderacion.py)."""
from django import forms

from Alumnos.forms import EstiloCamposMixin

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class FiltroModeracionForm(EstiloCamposMixin, forms.Form):
    persona = forms.CharField(required=False, max_length=100, label='Persona', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Buscar por persona…', 'autocomplete': 'off',
    }))
    texto = forms.CharField(required=False, max_length=200, label='Texto', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Buscar en el texto…', 'autocomplete': 'off',
    }))
    desde = forms.DateField(required=False, label='Desde', widget=FECHA)
    hasta = forms.DateField(required=False, label='Hasta', widget=FECHA)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
            datos['desde'], datos['hasta'] = datos['hasta'], datos['desde']   # al revés: se entiende el rango igual
        return datos

    @property
    def activos(self):
        """Los criterios válidos que se escribieron (los inválidos de la URL se ignoran)."""
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}
