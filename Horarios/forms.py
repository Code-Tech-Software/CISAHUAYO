from django import forms
from django.core.exceptions import ValidationError

from Alumnos.forms import EstiloCamposMixin
from Alumnos.horarios import (
    DIAS,
    bloques_del_profesor_empalmados,
    bloques_empalmados,
    mensaje_de_empalme_profesor,
)
from Alumnos.models import HorarioMateria, MateriaGrado

HORA = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')


class AsignacionChoiceField(forms.ModelChoiceField):
    """Selector de la materia de un grado: «Matemáticas (MAT)»."""

    def label_from_instance(self, asignacion):
        profesor = f' · {asignacion.profesor.apellido_paterno}' if asignacion.profesor_id else ''
        return f'{asignacion.materia.nombre} ({asignacion.materia.clave}){profesor}'


def asignaciones_del_grado(grado, ciclo):
    """Materias que el grado imparte de forma vigente en el ciclo."""
    return (
        MateriaGrado.objects.filter(grado=grado, ciclo=ciclo, activa=True)
        .select_related('materia', 'profesor').order_by('materia__nombre')
    )


def mensaje_de_empalme(bloques):
    partes = [
        f'{b.materia_grado.materia} ({DIAS[b.dia_semana].lower()} {b.hora_inicio:%H:%M}–{b.hora_fin:%H:%M})'
        for b in bloques
    ]
    return 'Se empalma con ' + ', '.join(partes) + ': un grado solo tiene un grupo y no puede estar en dos materias a la vez.'


# ---------------------------------------------------------------------------
# Agregar: una materia en uno o varios días con la misma hora
# ---------------------------------------------------------------------------
class HorarioCrearForm(EstiloCamposMixin, forms.Form):
    materia_grado = AsignacionChoiceField(
        MateriaGrado.objects.none(), label='Materia', empty_label='Selecciona una materia',
        error_messages={'required': 'Elige la materia.', 'invalid_choice': 'Elige una materia de la lista.'},
    )
    dias = forms.TypedMultipleChoiceField(
        choices=list(DIAS.items()), coerce=int, label='Días',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        error_messages={'required': 'Elige al menos un día.', 'invalid_choice': 'Elige días de la lista.'},
    )
    hora_inicio = forms.TimeField(label='Hora de inicio', widget=HORA, error_messages={'required': 'Indica la hora de inicio.', 'invalid': 'Escribe una hora válida.'})
    hora_fin = forms.TimeField(label='Hora de fin', widget=HORA, error_messages={'required': 'Indica la hora de fin.', 'invalid': 'Escribe una hora válida.'})

    def __init__(self, *args, grado, ciclo, **kwargs):
        super().__init__(*args, **kwargs)
        self.grado, self.ciclo = grado, ciclo
        self.fields['materia_grado'].queryset = asignaciones_del_grado(grado, ciclo)
        self.aplicar_estilo()
        self.fields['dias'].widget.attrs['class'] = 'choice__input'  # el mixin le habría puesto la clase de los campos de texto

    def clean(self):
        datos = super().clean()
        inicio, fin, dias = datos.get('hora_inicio'), datos.get('hora_fin'), datos.get('dias')
        if inicio and fin:
            if inicio >= fin:
                raise ValidationError('La hora de inicio debe ser anterior a la hora de fin.')
            if dias:
                empalmes = [b for dia in sorted(dias) for b in bloques_empalmados(self.grado, self.ciclo, dia, inicio, fin)]
                if empalmes:
                    self.add_error('hora_inicio', mensaje_de_empalme(empalmes))
                profesor = datos['materia_grado'].profesor if datos.get('materia_grado') else None
                if profesor:
                    del_profesor = [
                        b for dia in sorted(dias)
                        for b in bloques_del_profesor_empalmados(profesor, self.ciclo, dia, inicio, fin, excluir_grado=self.grado)
                    ]
                    if del_profesor:
                        self.add_error('hora_inicio', mensaje_de_empalme_profesor(profesor, del_profesor))
        return datos

    def guardar(self):
        datos = self.cleaned_data
        bloques = [
            HorarioMateria(
                materia_grado=datos['materia_grado'], dia_semana=dia,
                hora_inicio=datos['hora_inicio'], hora_fin=datos['hora_fin'],
            )
            for dia in sorted(datos['dias'])
        ]
        HorarioMateria.objects.bulk_create(bloques)
        return bloques


# ---------------------------------------------------------------------------
# Editar un bloque
# ---------------------------------------------------------------------------
class HorarioEditarForm(EstiloCamposMixin, forms.ModelForm):
    materia_grado = AsignacionChoiceField(
        MateriaGrado.objects.none(), label='Materia', empty_label=None,
        error_messages={'required': 'Elige la materia.', 'invalid_choice': 'Elige una materia de la lista.'},
    )

    class Meta:
        model = HorarioMateria
        fields = ['materia_grado', 'dia_semana', 'hora_inicio', 'hora_fin']
        widgets = {'hora_inicio': HORA, 'hora_fin': HORA}
        labels = {'dia_semana': 'Día'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        asignacion = self.instance.materia_grado
        self.grado, self.ciclo = asignacion.grado, asignacion.ciclo
        self.fields['materia_grado'].queryset = asignaciones_del_grado(self.grado, self.ciclo)
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        inicio, fin, dia = datos.get('hora_inicio'), datos.get('hora_fin'), datos.get('dia_semana')
        # El orden de las horas lo valida el modelo; aquí, que no se empalme con otra materia del grado.
        if inicio and fin and inicio < fin and dia is not None:
            empalmes = list(bloques_empalmados(self.grado, self.ciclo, dia, inicio, fin, excluir_pk=self.instance.pk))
            if empalmes:
                self.add_error('hora_inicio', mensaje_de_empalme(empalmes))
            asignacion = datos.get('materia_grado')
            if asignacion and asignacion.profesor:
                del_profesor = list(bloques_del_profesor_empalmados(
                    asignacion.profesor, self.ciclo, dia, inicio, fin, excluir_pk=self.instance.pk, excluir_grado=self.grado,
                ))
                if del_profesor:
                    self.add_error('hora_inicio', mensaje_de_empalme_profesor(asignacion.profesor, del_profesor))
        return datos
