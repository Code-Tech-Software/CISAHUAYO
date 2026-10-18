from django import forms

from Alumnos.forms import EstiloCamposMixin

from .models import ALCANCES, EventoAgenda

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
HORA = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')


class EventoForm(EstiloCamposMixin, forms.ModelForm):
    """Registrar o editar un evento. La finalización no puede ser anterior al inicio; sin «Todo el día», las horas son
    obligatorias (y con «Todo el día» se descartan)."""

    class Meta:
        model = EventoAgenda
        fields = ['titulo', 'descripcion', 'alcance', 'fecha_inicio', 'fecha_fin', 'todo_el_dia', 'hora_inicio', 'hora_fin', 'lugar']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 3}),
            'fecha_inicio': FECHA, 'fecha_fin': FECHA, 'hora_inicio': HORA, 'hora_fin': HORA,
            'todo_el_dia': forms.CheckboxInput(attrs={'class': 'choice__input', 'data-agenda-todo-el-dia': ''}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['alcance'].choices = [('', 'Elige el alcance'), *ALCANCES]
        self.fields['fecha_fin'].required = False
        self.fields['fecha_fin'].help_text = 'Vacía: el mismo día.'
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get('fecha_inicio'), datos.get('fecha_fin')
        if inicio and not fin:
            datos['fecha_fin'] = fin = inicio
        if inicio and fin and fin < inicio:
            self.add_error('fecha_fin', 'La fecha de finalización no puede ser anterior a la de inicio.')
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
