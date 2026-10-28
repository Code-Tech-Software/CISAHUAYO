import calendar
from datetime import timedelta

from django import forms

from Alumnos.forms import EstiloCamposMixin

from .models import ALCANCES, TIPOS, EventoAgenda
from .reglas import DIAS, HASTA_UN_ANIO, MENSUAL_ORDINAL, MENSUAL_ULTIMO, REPETICIONES

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
HORA = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')


class EventoForm(EstiloCamposMixin, forms.ModelForm):
    """Registrar o editar un evento. La finalización no puede ser anterior al inicio; sin «Todo el día», las horas son
    obligatorias (y con «Todo el día» se descartan). Al registrarlo se puede repetir (Agenda/reglas.py: hasta la fecha
    elegida, como máximo un año); al editar uno de una serie, se elige si los cambios van también a los siguientes."""

    repetir = forms.ChoiceField(label='Repetir', required=False, choices=[('', 'No se repite'), *REPETICIONES])
    repetir_hasta = forms.DateField(label='Hasta', required=False, widget=FECHA, input_formats=['%Y-%m-%d'])
    saltar_sin_clases = forms.BooleanField(label='Saltar los días sin clases', required=False, initial=True)
    toda_la_serie = forms.BooleanField(label='Aplicar los cambios también a los siguientes de la serie', required=False,
                                       help_text='Sus fechas no cambian: solo el título, la descripción, el alcance, el tipo, el horario, el lugar y el recordatorio.')

    class Meta:
        model = EventoAgenda
        fields = ['titulo', 'descripcion', 'alcance', 'tipo', 'fecha_inicio', 'fecha_fin', 'todo_el_dia', 'hora_inicio', 'hora_fin', 'lugar', 'importante']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 3}),
            'fecha_inicio': FECHA, 'fecha_fin': FECHA, 'hora_inicio': HORA, 'hora_fin': HORA,
            'todo_el_dia': forms.CheckboxInput(attrs={'class': 'choice__input', 'data-agenda-todo-el-dia': ''}),
            'importante': forms.CheckboxInput(attrs={'class': 'choice__input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['alcance'].choices = [('', 'Elige el alcance'), *ALCANCES]
        self.fields['tipo'].choices = [('', 'Otro (sin tipo)'), *TIPOS]
        self.fields['fecha_fin'].required = False
        self.fields['fecha_fin'].help_text = 'Vacía: el mismo día.'
        self.fields['descripcion'].help_text = 'Las direcciones (https://…) se podrán tocar.'
        self.fields['repetir'].widget.attrs['data-agenda-repetir'] = ''
        self.fields['saltar_sin_clases'].widget.attrs['class'] = 'choice__input'
        self.fields['toda_la_serie'].widget.attrs['class'] = 'choice__input'
        if self.instance.pk:   # editar: la repetición ya se eligió al registrarlo
            del self.fields['repetir'], self.fields['repetir_hasta'], self.fields['saltar_sin_clases']
            if not self.instance.serie:
                del self.fields['toda_la_serie']
        else:
            del self.fields['toda_la_serie']
        self.aplicar_estilo()

    @property
    def es_de_una_serie(self):
        return 'toda_la_serie' in self.fields

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get('fecha_inicio'), datos.get('fecha_fin')
        if inicio and not fin:
            datos['fecha_fin'] = fin = inicio
        if inicio and fin and fin < inicio:
            self.add_error('fecha_fin', 'La fecha de finalización no puede ser anterior a la de inicio.')
        repetir = datos.get('repetir')
        if repetir:
            hasta = datos.get('repetir_hasta')
            if not hasta:
                self.add_error('repetir_hasta', 'Elige hasta cuándo se repite.')
            elif inicio and hasta <= inicio:
                self.add_error('repetir_hasta', 'Debe ser después de la fecha de inicio.')
            elif inicio and hasta > inicio + timedelta(days=HASTA_UN_ANIO):
                self.add_error('repetir_hasta', 'Se puede repetir hasta un año después de la fecha de inicio.')
            if inicio and repetir == MENSUAL_ULTIMO and inicio.day + 7 <= calendar.monthrange(inicio.year, inicio.month)[1]:
                self.add_error('repetir', f'Esa fecha no es el último {DIAS[inicio.weekday()]} del mes: elige otra repetición o cambia la fecha.')
            if inicio and repetir == MENSUAL_ORDINAL and inicio.day > 28:
                self.add_error('repetir', f'Es el quinto {DIAS[inicio.weekday()]} del mes y no todos los meses lo tienen: '
                                          f'elige «Cada mes, el último {DIAS[inicio.weekday()]}».')
        if datos.get('todo_el_dia'):
            datos['hora_inicio'] = datos['hora_fin'] = None
            return datos
        hora_inicio, hora_fin = datos.get('hora_inicio'), datos.get('hora_fin')
        if hora_inicio is None:
            self.add_error('hora_inicio', 'Indica la hora de inicio (o marca «Todo el día»).')
        if hora_fin is None:
            self.add_error('hora_fin', 'Indica la hora de finalización (o marca «Todo el día»).')
        if hora_inicio and hora_fin and inicio and fin and inicio == fin and hora_fin <= hora_inicio:
            self.add_error('hora_fin', 'La hora de finalización debe ser posterior a la de inicio.')
        return datos
