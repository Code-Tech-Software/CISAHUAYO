from django import forms

import json

from Alumnos.academico import (
    BASE_DE_EQUIVALENCIA,
    FORMATO_EQUIVALENCIA,
    LARGO_EQUIVALENCIA,
    LIMITE_GRADOS,
    PREFIJO_DE_EQUIVALENCIA,
    equivalencia_sugerida,
    normalizar_equivalencia,
)
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Grado


class GradoForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición. La baja y la reactivación son acciones aparte (no hay borrado físico)."""

    class Meta:
        model = Grado
        fields = ['nivel', 'numero', 'equivalencia']
        labels = {'numero': 'Número de grado', 'equivalencia': 'Equivalencia en la continuidad escolar'}
        widgets = {
            'numero': forms.NumberInput(attrs={'min': 1, 'max': max(LIMITE_GRADOS.values()), 'inputmode': 'numeric'}),
            'equivalencia': forms.TextInput(attrs={
                'maxlength': LARGO_EQUIVALENCIA, 'autocomplete': 'off', 'autocapitalize': 'characters', 'spellcheck': 'false',
                'placeholder': 'Ej.: 7 o K1',
                # Lo usa static/js/grados-form.js para proponer la equivalencia habitual al elegir nivel y número
                'data-bases': json.dumps(BASE_DE_EQUIVALENCIA), 'data-prefijos': json.dumps(PREFIJO_DE_EQUIVALENCIA),
            }),
        }
        help_texts = {
            'nivel': 'El colegio tiene un solo grupo por grado, así que el grado es la unidad: no hay grupos ni secciones.',
            'numero': 'Preescolar y secundaria llegan hasta el 3.°; primaria, hasta el 6.°.',
            'equivalencia': (
                'Cómo se nombra este grado a lo largo de toda la trayectoria, sin importar el nivel: un número '
                '(1.° de secundaria es el 7) o un código con letras (K1 para 1.° de preescolar). Si la dejas vacía se propone la habitual.'
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nivel'].choices = [('', 'Selecciona un nivel'), *Grado.NIVEL_CHOICES]
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        nivel, numero = datos.get('nivel'), datos.get('numero')
        if nivel and numero is not None:  # el 0 también debe validarse
            nombre = dict(Grado.NIVEL_CHOICES)[nivel]
            limite = LIMITE_GRADOS[nivel]
            if not 1 <= numero <= limite:
                self.add_error('numero', f'En {nombre.lower()} los grados van del 1.° al {limite}.°.')
            elif Grado.objects.filter(nivel=nivel, numero=numero).exclude(pk=self.instance.pk).exists():
                self.add_error('numero', f'Ya existe el grado {numero}° {nombre}.')

        # Sin equivalencia escrita se propone la habitual del grado (primaria 1–6, secundaria 7–9, preescolar K1–K3...)
        if 'equivalencia' not in self.errors:
            equivalencia = datos.get('equivalencia') or equivalencia_sugerida(nivel, numero)
            datos['equivalencia'] = equivalencia
            if equivalencia:
                otro = Grado.objects.filter(activo=True, equivalencia=equivalencia).exclude(pk=self.instance.pk).first()
                if otro:
                    texto = Grado(equivalencia=equivalencia).equivalencia_texto
                    self.add_error('equivalencia', f'La equivalencia {texto} ya la tiene {otro}: cada grado tiene la suya.')
        return datos

    def clean_equivalencia(self):
        valor = normalizar_equivalencia(self.cleaned_data.get('equivalencia'))
        if valor and not FORMATO_EQUIVALENCIA.match(valor):
            raise forms.ValidationError('Usa solo letras y números, sin símbolos (7, 10, K1).')
        return valor
