from django import forms

from CISAHUAYO import temas
from Usuarios.models import PerfilUsuario


class AparienciaForm(forms.ModelForm):
    """El tema de color y el menú lateral de la persona. Se dibuja con tarjetas propias (ajustes/apariencia.html),
    no con los campos de siempre, así que no lleva el estilo de los demás formularios."""

    class Meta:
        model = PerfilUsuario
        fields = ['tema', 'menu_lateral']
        widgets = {'tema': forms.RadioSelect, 'menu_lateral': forms.RadioSelect}
        error_messages = {
            'tema': {'invalid_choice': 'Elige uno de los temas de la lista.', 'required': 'Elige un tema.'},
            'menu_lateral': {'invalid_choice': 'Elige cómo se ve el menú lateral.', 'required': 'Elige cómo se ve el menú lateral.'},
        }

    def opciones_de_tema(self):
        """Cada tema con su nombre, descripción y si es el elegido, para dibujar las tarjetas."""
        elegido = self['tema'].value()
        return [{**tema, 'elegido': tema['clave'] == elegido} for tema in temas.TEMAS]

    def opciones_de_menu(self):
        elegido = self['menu_lateral'].value()
        return [{'clave': clave, 'nombre': nombre, 'elegido': clave == elegido} for clave, nombre in temas.MENUS]
