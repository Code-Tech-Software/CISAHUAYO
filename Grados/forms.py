from django import forms

from Alumnos.academico import LIMITE_GRADOS
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Grado


class GradoForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición. La baja y la reactivación son acciones aparte (no hay borrado físico)."""

    class Meta:
        model = Grado
        fields = ['nivel', 'numero']
        labels = {'numero': 'Número de grado'}
        widgets = {'numero': forms.NumberInput(attrs={'min': 1, 'max': max(LIMITE_GRADOS.values()), 'inputmode': 'numeric'})}
        help_texts = {
            'nivel': 'El colegio tiene un solo grupo por grado, así que el grado es la unidad: no hay grupos ni secciones.',
            'numero': 'Preescolar y secundaria llegan hasta el 3.°; primaria, hasta el 6.°.',
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
        return datos
