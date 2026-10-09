from django import forms
from django.core.exceptions import ValidationError

from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Grado, Periodo
from Alumnos.periodos import fechas_sugeridas
from Alumnos.utils import compactar_espacios

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class PeriodoForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición de un periodo de evaluación de un nivel, dentro de un ciclo.

    Sus fechas deben caer dentro del ciclo y no empalmarse con otro periodo del mismo nivel; el nombre no se repite en
    el nivel. Abrirlo o cerrarlo a mano son acciones aparte (ver Periodos/views.py).
    """

    class Meta:
        model = Periodo
        fields = ['nivel', 'nombre', 'fecha_inicio', 'fecha_fin']
        widgets = {
            'nivel': forms.RadioSelect(attrs={'class': 'choice__input'}),
            'nombre': forms.TextInput(attrs={'placeholder': 'Primer bimestre', 'autocomplete': 'off'}),
            'fecha_inicio': FECHA,
            'fecha_fin': FECHA,
        }
        labels = {'fecha_inicio': 'Se abre el', 'fecha_fin': 'Se cierra el'}
        help_texts = {
            'nombre': 'Como lo llame el colegio: «Primer parcial», «Segundo bimestre», «Tercer trimestre»…',
            'fecha_inicio': 'Desde este día los profesores del nivel pueden capturar.',
            'fecha_fin': 'Al terminar este día se cierra la captura (puedes abrirlo de nuevo a mano).',
        }
        error_messages = {
            'nivel': {'required': 'Elige el nivel.'},
            'nombre': {'required': 'Escribe el nombre del periodo.'},
            'fecha_inicio': {'required': 'Indica cuándo se abre.', 'invalid': 'Escribe una fecha válida.'},
            'fecha_fin': {'required': 'Indica cuándo se cierra.', 'invalid': 'Escribe una fecha válida.'},
        }

    def __init__(self, *args, ciclo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = self.instance._state.adding
        if self.creando:
            self.instance.ciclo = ciclo
        self.ciclo = self.instance.ciclo
        self.fields['nivel'].choices = [opcion for opcion in self.fields['nivel'].choices if opcion[0]]   # sin «---------»
        # Al agregar uno a un nivel, se propone que empiece el día siguiente al último que ya tiene
        nivel = self.initial.get('nivel')
        if self.creando and not self.is_bound and nivel:
            self.initial.update(fechas_sugeridas(self.ciclo, nivel))
        self.aplicar_estilo()
        self.fields['nivel'].widget.attrs['class'] = 'choice__input'   # el mixin le habría puesto la clase de los campos de texto

    def clean_nombre(self):
        return compactar_espacios(self.cleaned_data.get('nombre'))

    def clean(self):
        datos = super().clean()
        nivel, nombre = datos.get('nivel'), datos.get('nombre')
        inicio, fin = datos.get('fecha_inicio'), datos.get('fecha_fin')
        otros = Periodo.objects.filter(ciclo=self.ciclo, nivel=nivel).exclude(pk=self.instance.pk)

        if nivel and nombre and otros.filter(nombre__iexact=nombre).exists():
            self.add_error('nombre', f'{dict(Grado.NIVEL_CHOICES)[nivel]} ya tiene un periodo con ese nombre en el ciclo {self.ciclo}.')

        if inicio and fin:
            if fin < inicio:
                self.add_error('fecha_fin', 'La fecha de cierre no puede ser anterior a la de inicio.')
                return datos
            ciclo = self.ciclo
            if inicio < ciclo.fecha_inicio or fin > ciclo.fecha_fin:
                raise ValidationError(
                    f'Las fechas deben quedar dentro del ciclo {ciclo} ({ciclo.fecha_inicio:%d/%m/%Y} al {ciclo.fecha_fin:%d/%m/%Y}).'
                )
            if nivel:
                empalmado = otros.filter(fecha_inicio__lte=fin, fecha_fin__gte=inicio).order_by('fecha_inicio').first()
                if empalmado:
                    self.add_error('fecha_inicio', (
                        f'Se empalma con «{empalmado.nombre}» ({empalmado.fecha_inicio:%d/%m/%Y} al '
                        f'{empalmado.fecha_fin:%d/%m/%Y}): los periodos de un nivel van uno después de otro.'
                    ))
        return datos
