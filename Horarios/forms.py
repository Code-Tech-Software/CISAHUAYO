from django import forms

from Alumnos.forms import EstiloCamposMixin
from Alumnos.horarios import (
    DIAS,
    bloques_del_profesor_empalmados,
    bloques_empalmados,
    mensaje_de_empalme_profesor,
    recreos_empalmados,
)
from Alumnos.models import Grado, HorarioMateria, MateriaGrado, Recreo

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


def _franja(bloque):
    return f'{DIAS[bloque.dia_semana].lower()} {bloque.hora_inicio:%H:%M}–{bloque.hora_fin:%H:%M}'


def mensaje_de_empalme(bloques, recreos=()):
    """Con qué se empalma, en el horario del grupo: otras materias del grado o sus recreos."""
    partes = [f'{b.materia_grado.materia} ({_franja(b)})' for b in bloques]
    partes += [f'el {r.nombre.lower()} ({_franja(r)})' for r in recreos]
    if bloques:
        return 'Se empalma con ' + ', '.join(partes) + ': un grado solo tiene un grupo y no puede estar en dos materias a la vez.'
    return 'Se empalma con ' + ', '.join(partes) + ': a esa hora el grupo está en recreo.'


def empalmes_del_grupo(grado, ciclo, dia, inicio, fin, excluir_bloque=None, excluir_recreo=None):
    """(bloques de materias, recreos) del grado que se empalman con el intervalo, o ([], []) si está libre."""
    return (
        list(bloques_empalmados(grado, ciclo, dia, inicio, fin, excluir_pk=excluir_bloque)),
        list(recreos_empalmados(grado, ciclo, dia, inicio, fin, excluir_pk=excluir_recreo)),
    )


# ---------------------------------------------------------------------------
# Días con su propia hora cada uno (alta de una materia y de un recreo)
# ---------------------------------------------------------------------------
def campo_de_dias():
    return forms.TypedMultipleChoiceField(
        choices=list(DIAS.items()), coerce=int, label='Días',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        error_messages={'required': 'Elige al menos un día.', 'invalid_choice': 'Elige días de la lista.'},
    )


class HorasPorDiaMixin:
    """Los días marcados (`dias`) con su propia hora de inicio y de fin cada uno (`inicio_<día>` y `fin_<día>`, con el
    número del día: 0 = lunes). Solo cuentan las de los días marcados: las de los demás se ignoran.

    Se usa con la plantilla `horarios/_horas_por_dia.html` y `static/js/horario-form.js`.
    """

    def agregar_horas_por_dia(self):
        for dia in DIAS:
            for campo, etiqueta in (('inicio', 'Hora de inicio'), ('fin', 'Hora de fin')):
                self.fields[f'{campo}_{dia}'] = forms.TimeField(
                    required=False, label=etiqueta, widget=HORA, error_messages={'invalid': 'Escribe una hora válida.'},
                )

    @property
    def dias_marcados(self):
        """Los días marcados según lo enviado (o lo inicial), aunque el formulario todavía no se haya validado."""
        return {int(valor) for valor in (self['dias'].value() or []) if str(valor).isdigit()}

    @property
    def horas_por_dia(self):
        """Una fila por día de la semana con sus dos campos; la plantilla muestra solo las de los días marcados."""
        marcados = self.dias_marcados
        return [
            {'dia': dia, 'nombre': nombre, 'marcado': dia in marcados, 'inicio': self[f'inicio_{dia}'], 'fin': self[f'fin_{dia}']}
            for dia, nombre in DIAS.items()
        ]

    def limpiar_horas_por_dia(self, datos):
        """Revisa que cada día marcado tenga sus dos horas y que la de fin sea posterior. Devuelve [(día, inicio, fin)]
        de los días correctos."""
        dias = sorted(datos.get('dias') or [])
        # Lo escrito en un día sin marcar no se guarda, así que tampoco se le piden correcciones
        for dia in set(DIAS) - set(dias):
            for campo in (f'inicio_{dia}', f'fin_{dia}'):
                self._errors.pop(campo, None)

        correctos = []
        for dia in dias:
            nombre = DIAS[dia].lower()
            inicio, fin = datos.get(f'inicio_{dia}'), datos.get(f'fin_{dia}')
            if inicio is None and f'inicio_{dia}' not in self.errors:
                self.add_error(f'inicio_{dia}', f'Indica la hora de inicio del {nombre}.')
            if fin is None and f'fin_{dia}' not in self.errors:
                self.add_error(f'fin_{dia}', f'Indica la hora de fin del {nombre}.')
            if inicio and fin:
                if fin <= inicio:
                    self.add_error(f'fin_{dia}', f'La hora de fin del {nombre} debe ser posterior a la de inicio.')
                else:
                    correctos.append((dia, inicio, fin))
        return correctos


# ---------------------------------------------------------------------------
# Agregar: una materia en uno o varios días, cada día con su propia hora
# ---------------------------------------------------------------------------
class HorarioCrearForm(HorasPorDiaMixin, EstiloCamposMixin, forms.Form):
    """Una materia en los días marcados, cada uno con su hora (ver `HorasPorDiaMixin`).

    Se guarda todo o nada: si un día se empalma con otra materia o un recreo del grado, o con otra clase del profesor,
    no se guarda ninguno.
    """

    materia_grado = AsignacionChoiceField(
        MateriaGrado.objects.none(), label='Materia', empty_label='Selecciona una materia',
        error_messages={'required': 'Elige la materia.', 'invalid_choice': 'Elige una materia de la lista.'},
    )
    dias = campo_de_dias()

    def __init__(self, *args, grado, ciclo, **kwargs):
        super().__init__(*args, **kwargs)
        self.grado, self.ciclo = grado, ciclo
        self.bloques_pedidos = []   # (día, inicio, fin) de cada día marcado, ya validados
        self.fields['materia_grado'].queryset = asignaciones_del_grado(grado, ciclo)
        self.agregar_horas_por_dia()
        self.aplicar_estilo()
        self.fields['dias'].widget.attrs['class'] = 'choice__input'  # el mixin le habría puesto la clase de los campos de texto

    def clean(self):
        datos = super().clean()
        self.bloques_pedidos = self.limpiar_horas_por_dia(datos)

        # Empalmes, día por día: con el grupo (otra materia o un recreo del grado) y con otra clase del profesor
        profesor = datos['materia_grado'].profesor if datos.get('materia_grado') else None
        for dia, inicio, fin in self.bloques_pedidos:
            bloques, recreos = empalmes_del_grupo(self.grado, self.ciclo, dia, inicio, fin)
            if bloques or recreos:
                self.add_error(f'inicio_{dia}', mensaje_de_empalme(bloques, recreos))
            if profesor:
                del_profesor = list(bloques_del_profesor_empalmados(profesor, self.ciclo, dia, inicio, fin, excluir_grado=self.grado))
                if del_profesor:
                    self.add_error(f'inicio_{dia}', mensaje_de_empalme_profesor(profesor, del_profesor))
        return datos

    def guardar(self):
        bloques = [
            HorarioMateria(materia_grado=self.cleaned_data['materia_grado'], dia_semana=dia, hora_inicio=inicio, hora_fin=fin)
            for dia, inicio, fin in self.bloques_pedidos
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
        # El orden de las horas lo valida el modelo; aquí, que no se empalme con otra materia ni con un recreo del grado.
        if inicio and fin and inicio < fin and dia is not None:
            bloques, recreos = empalmes_del_grupo(self.grado, self.ciclo, dia, inicio, fin, excluir_bloque=self.instance.pk)
            if bloques or recreos:
                self.add_error('hora_inicio', mensaje_de_empalme(bloques, recreos))
            asignacion = datos.get('materia_grado')
            if asignacion and asignacion.profesor:
                del_profesor = list(bloques_del_profesor_empalmados(
                    asignacion.profesor, self.ciclo, dia, inicio, fin, excluir_pk=self.instance.pk, excluir_grado=self.grado,
                ))
                if del_profesor:
                    self.add_error('hora_inicio', mensaje_de_empalme_profesor(asignacion.profesor, del_profesor))
        return datos


# ---------------------------------------------------------------------------
# Recreos: se agregan a uno o varios grados a la vez, cada día con su hora
# ---------------------------------------------------------------------------
class RecreoCrearForm(HorasPorDiaMixin, EstiloCamposMixin, forms.Form):
    """El recreo de uno o varios grupos (grados) en el ciclo, en los días marcados y cada día con su hora.

    Ocupa el horario de cada grupo: no se puede empalmar con sus materias ni con otro recreo suyo. Se guarda todo o
    nada: si en un grado algún día choca, no se guarda en ninguno.
    """

    grados = forms.ModelMultipleChoiceField(
        Grado.objects.none(), label='Grupos que salen al recreo',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        error_messages={'required': 'Elige al menos un grado.', 'invalid_choice': 'Elige grados de la lista.'},
    )
    nombre = forms.CharField(
        max_length=40, initial='Recreo', label='Nombre', help_text='Cómo aparece en el horario: «Recreo», «Recreo largo», «Almuerzo»…',
        error_messages={'required': 'Escribe el nombre (por ejemplo, «Recreo»).'},
    )
    dias = campo_de_dias()

    def __init__(self, *args, ciclo, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciclo = ciclo
        self.recreos_pedidos = []   # (día, inicio, fin) de cada día marcado, ya validados
        self.fields['grados'].queryset = Grado.objects.filter(activo=True).academicos()
        self.agregar_horas_por_dia()
        self.aplicar_estilo()
        for campo in ('grados', 'dias'):
            self.fields[campo].widget.attrs['class'] = 'choice__input'

    @property
    def grados_por_nivel(self):
        """Las casillas de los grados agrupadas por nivel: [{'nombre': 'Primaria', 'casillas': [...]}, ...]."""
        niveles = dict(self.fields['grados'].queryset.values_list('pk', 'nivel'))
        nombres = dict(Grado.NIVEL_CHOICES)
        grupos = []
        for casilla in self['grados']:
            nombre = nombres[niveles[int(str(casilla.data['value']))]]
            if not grupos or grupos[-1]['nombre'] != nombre:
                grupos.append({'nombre': nombre, 'casillas': []})
            grupos[-1]['casillas'].append(casilla)
        return grupos

    def clean_nombre(self):
        return ' '.join(self.cleaned_data.get('nombre', '').split())

    def clean(self):
        datos = super().clean()
        self.recreos_pedidos = self.limpiar_horas_por_dia(datos)
        for grado in datos.get('grados') or []:
            for dia, inicio, fin in self.recreos_pedidos:
                bloques, recreos = empalmes_del_grupo(grado, self.ciclo, dia, inicio, fin)
                if bloques or recreos:
                    self.add_error(f'inicio_{dia}', f'En {grado}: {mensaje_de_empalme(bloques, recreos)}')
        return datos

    def guardar(self):
        recreos = [
            Recreo(ciclo=self.ciclo, grado=grado, nombre=self.cleaned_data['nombre'], dia_semana=dia, hora_inicio=inicio, hora_fin=fin)
            for grado in self.cleaned_data['grados']
            for dia, inicio, fin in self.recreos_pedidos
        ]
        Recreo.objects.bulk_create(recreos)
        return recreos


class RecreoEditarForm(EstiloCamposMixin, forms.ModelForm):
    """Un recreo de un grado: su nombre, su día y su hora."""

    class Meta:
        model = Recreo
        fields = ['nombre', 'dia_semana', 'hora_inicio', 'hora_fin']
        widgets = {'hora_inicio': HORA, 'hora_fin': HORA}
        help_texts = {'nombre': 'Cómo aparece en el horario: «Recreo», «Recreo largo», «Almuerzo»…'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_nombre(self):
        return ' '.join(self.cleaned_data.get('nombre', '').split())

    def clean(self):
        datos = super().clean()
        inicio, fin, dia = datos.get('hora_inicio'), datos.get('hora_fin'), datos.get('dia_semana')
        # El orden de las horas lo valida el modelo; aquí, que no se empalme con una materia ni con otro recreo del grado.
        if inicio and fin and inicio < fin and dia is not None:
            bloques, recreos = empalmes_del_grupo(
                self.instance.grado, self.instance.ciclo, dia, inicio, fin, excluir_recreo=self.instance.pk,
            )
            if bloques or recreos:
                self.add_error('hora_inicio', mensaje_de_empalme(bloques, recreos))
        return datos
