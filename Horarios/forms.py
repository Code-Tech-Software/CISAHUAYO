from django import forms

from Alumnos.forms import EstiloCamposMixin
from Alumnos.horarios import (
    DIAS,
    bloques_del_profesor_empalmados,
    bloques_empalmados,
    mensaje_de_empalme_profesor,
    recreos_empalmados,
)
from Alumnos.models import ConfiguracionHorario, ExcepcionSemana, Grado, Grupo, HorarioMateria, MateriaGrado, Recreo

from . import cambios

HORA = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')
FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class AsignacionChoiceField(forms.ModelChoiceField):
    """Selector de la materia de un grupo: «Matemáticas (MAT)»."""

    def label_from_instance(self, asignacion):
        profesor = f' · {asignacion.profesor.apellido_paterno}' if asignacion.profesor_id else ''
        return f'{asignacion.materia.nombre} ({asignacion.materia.clave}){profesor}'


def asignaciones_del_grupo(grupo, ciclo):
    """Materias que el grupo imparte de forma vigente en el ciclo."""
    return (
        MateriaGrado.objects.filter(grupo=grupo, ciclo=ciclo, activa=True)
        .select_related('materia', 'profesor').order_by('materia__nombre')
    )


def _franja(bloque):
    return f'{DIAS[bloque.dia_semana].lower()} {bloque.hora_inicio:%H:%M}–{bloque.hora_fin:%H:%M}'


def mensaje_de_empalme(bloques, recreos=()):
    """Con qué se empalma, en el horario del grupo: otras materias del grupo o sus recesos."""
    partes = [f'{b.materia_grado.materia} ({_franja(b)}{", semana " + b.semana if b.semana else ""})' for b in bloques]
    partes += [f'el {r.nombre.lower()} ({_franja(r)})' for r in recreos]
    if bloques:
        return 'Se empalma con ' + ', '.join(partes) + ': un grupo no puede estar en dos materias a la vez.'
    return 'Se empalma con ' + ', '.join(partes) + ': a esa hora el grupo está en receso.'


def empalmes_del_grupo(grupo, ciclo, dia, inicio, fin, excluir_bloque=None, excluir_recreo=None, semana=''):
    """(bloques de materias, recesos) del grupo que se empalman con el intervalo, o ([], []) si está libre. Con `semana`
    (A o B), solo cuentan los bloques de esa semana y los de todas; los recesos son de todas las semanas."""
    return (
        list(bloques_empalmados(grupo, ciclo, dia, inicio, fin, excluir_pk=excluir_bloque, semana=semana)),
        list(recreos_empalmados(grupo, ciclo, dia, inicio, fin, excluir_pk=excluir_recreo)),
    )


def campo_de_vigencia():
    """Desde cuándo aplica un cambio del horario (Horarios/cambios.py)."""
    return forms.DateField(
        required=False, label='Aplica desde', widget=FECHA,
        help_text='El horario anterior se conserva para las fechas previas. Déjalo vacío para corregir el horario de todo el ciclo.',
        error_messages={'invalid': 'Escribe una fecha válida.'},
    )


def validar_vigencia(form, ciclo):
    fecha = form.cleaned_data.get('vigencia')
    if fecha and ciclo and not ciclo.fecha_inicio <= fecha <= ciclo.fecha_fin:
        form.add_error('vigencia', f'Elige una fecha dentro del ciclo {ciclo} ({ciclo.fecha_inicio:%d/%m/%Y} a {ciclo.fecha_fin:%d/%m/%Y}).')
    return fecha


# ---------------------------------------------------------------------------
# Días con su propia hora cada uno (alta de una materia y de un receso)
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

    Se guarda todo o nada: si un día se empalma con otra materia o un receso del grupo, o con otra clase del profesor,
    no se guarda ninguno.
    """

    materia_grado = AsignacionChoiceField(
        MateriaGrado.objects.none(), label='Materia', empty_label='Selecciona una materia',
        error_messages={'required': 'Elige la materia.', 'invalid_choice': 'Elige una materia de la lista.'},
    )
    dias = campo_de_dias()
    vigencia = campo_de_vigencia()

    def __init__(self, *args, grupo, ciclo, semana='', **kwargs):
        super().__init__(*args, **kwargs)
        self.grupo, self.ciclo, self.semana = grupo, ciclo, semana   # semana: 'A' o 'B' en un horario alternado
        self.bloques_pedidos = []   # (día, inicio, fin) de cada día marcado, ya validados
        self.fields['materia_grado'].queryset = asignaciones_del_grupo(grupo, ciclo)
        self.agregar_horas_por_dia()
        self.aplicar_estilo()
        self.fields['dias'].widget.attrs['class'] = 'choice__input'  # el mixin le habría puesto la clase de los campos de texto

    def clean(self):
        datos = super().clean()
        self.bloques_pedidos = self.limpiar_horas_por_dia(datos)
        desde = validar_vigencia(self, self.ciclo)

        # Empalmes, día por día: con el grupo (otra materia o un receso suyo) y con otra clase del profesor
        profesor = datos['materia_grado'].profesor if datos.get('materia_grado') else None
        for dia, inicio, fin in self.bloques_pedidos:
            bloques, recreos = empalmes_del_grupo(self.grupo, self.ciclo, dia, inicio, fin, semana=self.semana)
            if bloques or recreos:
                self.add_error(f'inicio_{dia}', mensaje_de_empalme(bloques, recreos))
            if profesor:
                del_profesor = list(bloques_del_profesor_empalmados(
                    profesor, self.ciclo, dia, inicio, fin, excluir_grupo=self.grupo,
                    semana=self.semana, nivel=self.grupo.grado.nivel, desde=desde,
                ))
                if del_profesor:
                    self.add_error(f'inicio_{dia}', mensaje_de_empalme_profesor(profesor, del_profesor))
        return datos

    def guardar(self):
        return [
            cambios.crear(self.cleaned_data['materia_grado'], dia, inicio, fin, semana=self.semana, desde=self.cleaned_data.get('vigencia'))
            for dia, inicio, fin in self.bloques_pedidos
        ]


# ---------------------------------------------------------------------------
# Editar un bloque
# ---------------------------------------------------------------------------
class HorarioEditarForm(EstiloCamposMixin, forms.ModelForm):
    """Un bloque: su materia, día y horas (y su semana, en un horario alternado), desde la fecha que se indique."""

    materia_grado = AsignacionChoiceField(
        MateriaGrado.objects.none(), label='Materia', empty_label=None,
        error_messages={'required': 'Elige la materia.', 'invalid_choice': 'Elige una materia de la lista.'},
    )
    vigencia = campo_de_vigencia()

    class Meta:
        model = HorarioMateria
        fields = ['materia_grado', 'semana', 'dia_semana', 'hora_inicio', 'hora_fin']
        widgets = {'hora_inicio': HORA, 'hora_fin': HORA}
        labels = {'dia_semana': 'Día'}

    def __init__(self, *args, alternado=False, **kwargs):
        super().__init__(*args, **kwargs)
        asignacion = self.instance.materia_grado
        self.grupo, self.ciclo = asignacion.grupo, asignacion.ciclo
        self.fields['materia_grado'].queryset = asignaciones_del_grupo(self.grupo, self.ciclo)
        if alternado:
            self.fields['semana'].choices = HorarioMateria.SEMANA_CHOICES[1:]
            self.fields['semana'].required = True
        else:
            del self.fields['semana']   # horario fijo: todas las semanas
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        inicio, fin, dia = datos.get('hora_inicio'), datos.get('hora_fin'), datos.get('dia_semana')
        semana = datos.get('semana', self.instance.semana) or ''
        desde = validar_vigencia(self, self.ciclo)
        # El orden de las horas lo valida el modelo; aquí, que no se empalme con otra materia ni con un receso del grupo.
        if inicio and fin and inicio < fin and dia is not None:
            bloques, recreos = empalmes_del_grupo(self.grupo, self.ciclo, dia, inicio, fin, excluir_bloque=self.instance.pk, semana=semana)
            if bloques or recreos:
                self.add_error('hora_inicio', mensaje_de_empalme(bloques, recreos))
            asignacion = datos.get('materia_grado')
            if asignacion and asignacion.profesor:
                del_profesor = list(bloques_del_profesor_empalmados(
                    asignacion.profesor, self.ciclo, dia, inicio, fin, excluir_pk=self.instance.pk, excluir_grupo=self.grupo,
                    semana=semana, nivel=self.grupo.grado.nivel, desde=desde,
                ))
                if del_profesor:
                    self.add_error('hora_inicio', mensaje_de_empalme_profesor(asignacion.profesor, del_profesor))
        return datos

    def save(self, commit=True):
        """Con versiones: si aplica desde una fecha, el bloque anterior se conserva para las fechas previas."""
        valores = {campo: self.cleaned_data[campo] for campo in ('materia_grado', 'dia_semana', 'hora_inicio', 'hora_fin', 'semana')
                   if campo in self.cleaned_data}
        return cambios.cambiar(self.instance, desde=self.cleaned_data.get('vigencia'), **valores)


# ---------------------------------------------------------------------------
# Recesos: se agregan a uno o varios grupos a la vez, cada día con su hora
# ---------------------------------------------------------------------------
class GrupoCasillaField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, grupo):
        return grupo.corto


class RecreoCrearForm(HorasPorDiaMixin, EstiloCamposMixin, forms.Form):
    """El receso de uno o varios grupos en el ciclo, en los días marcados y cada día con su hora.

    Ocupa el horario de cada grupo: no se puede empalmar con sus materias ni con otro receso suyo. Se guarda todo o
    nada: si en un grupo algún día choca, no se guarda en ninguno.
    """

    grupos = GrupoCasillaField(
        Grupo.objects.none(), label='Grupos que salen al receso',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        error_messages={'required': 'Elige al menos un grupo.', 'invalid_choice': 'Elige grupos de la lista.'},
    )
    nombre = forms.CharField(
        max_length=40, initial='Receso', label='Nombre', help_text='Cómo aparece en el horario: «Receso», «Receso largo», «Almuerzo»…',
        error_messages={'required': 'Escribe el nombre (por ejemplo, «Receso»).'},
    )
    dias = campo_de_dias()

    def __init__(self, *args, ciclo, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciclo = ciclo
        self.recreos_pedidos = []   # (día, inicio, fin) de cada día marcado, ya validados
        self.fields['grupos'].queryset = Grupo.objects.disponibles().select_related('grado', 'nombre').academicos()
        self.agregar_horas_por_dia()
        self.aplicar_estilo()
        for campo in ('grupos', 'dias'):
            self.fields[campo].widget.attrs['class'] = 'choice__input'

    @property
    def grupos_por_nivel(self):
        """Las casillas de los grupos agrupadas por nivel: [{'nombre': 'Primaria', 'casillas': [...]}, ...]."""
        niveles = dict(self.fields['grupos'].queryset.values_list('pk', 'grado__nivel'))
        nombres = dict(Grado.NIVEL_CHOICES)
        grupos = []
        for casilla in self['grupos']:
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
        for grupo in datos.get('grupos') or []:
            for dia, inicio, fin in self.recreos_pedidos:
                bloques, recreos = empalmes_del_grupo(grupo, self.ciclo, dia, inicio, fin)
                if bloques or recreos:
                    self.add_error(f'inicio_{dia}', f'En {grupo}: {mensaje_de_empalme(bloques, recreos)}')
        return datos

    def guardar(self):
        recreos = [
            Recreo(
                ciclo=self.ciclo, grado_id=grupo.grado_id, grupo=grupo, nombre=self.cleaned_data['nombre'],
                dia_semana=dia, hora_inicio=inicio, hora_fin=fin,
            )
            for grupo in self.cleaned_data['grupos']
            for dia, inicio, fin in self.recreos_pedidos
        ]
        Recreo.objects.bulk_create(recreos)
        return recreos


class RecreoEditarForm(EstiloCamposMixin, forms.ModelForm):
    """Un receso de un grupo: su nombre, su día y su hora."""

    class Meta:
        model = Recreo
        fields = ['nombre', 'dia_semana', 'hora_inicio', 'hora_fin']
        widgets = {'hora_inicio': HORA, 'hora_fin': HORA}
        help_texts = {'nombre': 'Cómo aparece en el horario: «Receso», «Receso largo», «Almuerzo»…'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_nombre(self):
        return ' '.join(self.cleaned_data.get('nombre', '').split())

    def clean(self):
        datos = super().clean()
        inicio, fin, dia = datos.get('hora_inicio'), datos.get('hora_fin'), datos.get('dia_semana')
        # El orden de las horas lo valida el modelo; aquí, que no se empalme con una materia ni con otro receso del grupo.
        if inicio and fin and inicio < fin and dia is not None:
            bloques, recreos = empalmes_del_grupo(
                self.instance.grupo, self.instance.ciclo, dia, inicio, fin, excluir_recreo=self.instance.pk,
            )
            if bloques or recreos:
                self.add_error('hora_inicio', mensaje_de_empalme(bloques, recreos))
        return datos


# ---------------------------------------------------------------------------
# Semanas A y B: modalidad de un nivel en un ciclo y excepciones (Alumnos/semanas.py)
# ---------------------------------------------------------------------------
class ConfiguracionHorarioForm(EstiloCamposMixin, forms.ModelForm):
    """Horario fijo o alternado A/B de un nivel en un ciclo, con la semana de referencia."""

    class Meta:
        model = ConfiguracionHorario
        fields = ['modalidad', 'fecha_referencia', 'semana_referencia']
        widgets = {'fecha_referencia': FECHA}
        help_texts = {
            'fecha_referencia': 'Cualquier día de una semana del ciclo; las semanas van de lunes a domingo.',
            'semana_referencia': 'Desde esa semana se alternan las demás: A, B, A, B…, hacia adelante y hacia atrás.',
        }

    def __init__(self, *args, ciclo, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciclo = ciclo
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        if datos.get('modalidad') == ConfiguracionHorario.ALTERNADO:
            fecha = datos.get('fecha_referencia')
            if fecha is None:
                if 'fecha_referencia' not in self.errors:
                    self.add_error('fecha_referencia', 'Indica una fecha de referencia para saber qué semana es la A.')
            elif self.ciclo and not self.ciclo.fecha_inicio <= fecha <= self.ciclo.fecha_fin:
                self.add_error('fecha_referencia', f'Elige una fecha dentro del ciclo {self.ciclo}.')
        return datos


class ExcepcionSemanaForm(EstiloCamposMixin, forms.Form):
    """Una semana que no sigue la alternancia."""

    fecha = forms.DateField(label='Semana del', widget=FECHA, help_text='Cualquier día de esa semana (de lunes a domingo).',
                            error_messages={'required': 'Elige la semana.', 'invalid': 'Escribe una fecha válida.'})
    semana = forms.ChoiceField(label='Será la', choices=HorarioMateria.SEMANA_CHOICES[1:])
    tipo = forms.ChoiceField(label='Tipo de cambio', choices=ExcepcionSemana.TIPO_CHOICES, initial=ExcepcionSemana.SOLO_ESTA,
                             widget=forms.RadioSelect(attrs={'class': 'choice__input'}))
    motivo = forms.CharField(label='Motivo', max_length=200, required=False,
                             widget=forms.TextInput(attrs={'placeholder': 'Opcional: por qué cambia'}))

    def __init__(self, *args, ciclo, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciclo = ciclo
        self.aplicar_estilo()
        self.fields['tipo'].widget.attrs['class'] = 'choice__input'

    def clean_fecha(self):
        fecha = self.cleaned_data['fecha']
        if self.ciclo and not self.ciclo.fecha_inicio <= fecha <= self.ciclo.fecha_fin:
            raise forms.ValidationError(f'Elige una semana del ciclo {self.ciclo}.')
        return fecha

    def clean_motivo(self):
        return ' '.join(self.cleaned_data.get('motivo', '').split())
