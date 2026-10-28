"""Formularios de la mensajería: la búsqueda y la lista de conversaciones de la moderación (Mensajes/views_moderacion.py)
y el horario de atención (Ajustes › Mensajes)."""
from django import forms

from Alumnos.forms import EstiloCamposMixin

from .models import ConfiguracionMensajes
from .moderacion import ESTADOS_DE_CONVERSACION, TIPOS_DE_CONVERSACION

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


class FiltroConversacionesForm(EstiloCamposMixin, forms.Form):
    """Recorrer todas las conversaciones en la moderación: por persona, por con quién son y las que esperan respuesta."""

    persona = forms.CharField(required=False, max_length=100, label='Persona', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Buscar por persona…', 'autocomplete': 'off',
    }))
    tipo = forms.ChoiceField(required=False, label='Con quién', choices=[('', 'Todas las conversaciones'), *TIPOS_DE_CONVERSACION])
    estado = forms.ChoiceField(required=False, label='Respuesta', choices=[('', 'Con o sin respuesta'), *ESTADOS_DE_CONVERSACION])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    @property
    def activos(self):
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}


class ConfiguracionMensajesForm(EstiloCamposMixin, forms.ModelForm):
    """El horario de atención de la mensajería y los días hábiles para responder (Ajustes › Mensajes)."""

    class Meta:
        model = ConfiguracionMensajes
        fields = ['avisar_fuera_de_horario', 'hora_inicio', 'hora_fin', 'dias_para_responder']
        widgets = {
            'avisar_fuera_de_horario': forms.CheckboxInput(attrs={'class': 'choice__input'}),
            'hora_inicio': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'hora_fin': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'dias_para_responder': forms.NumberInput(attrs={'min': 1, 'max': 15, 'inputmode': 'numeric'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        if datos.get('hora_inicio') and datos.get('hora_fin') and datos['hora_fin'] <= datos['hora_inicio']:
            self.add_error('hora_fin', 'Debe ser después de la hora de inicio.')
        return datos
