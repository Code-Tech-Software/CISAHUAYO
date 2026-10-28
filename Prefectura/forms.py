"""Formularios de prefectura: el alcance de una cuenta (lo define el administrador), los accesos al colegio, la
justificación de faltas y retardos, su revocación y los filtros de las listas. El servidor valida todo: que el
estudiante esté en el alcance, que las fechas sean del ciclo actual y no futuras, y el comprobante (una foto)."""
from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from Alumnos.academico import ciclo_actual
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Alumno, DiaNoLectivo, Grado, Grupo, MateriaGrado, Periodo, orden_de_nivel
from Conducta.forms import FECHA, HORA, TAMANO_MAXIMO_MB, validar_archivo

from .alcance import NIVELES
from .asistencia import DIAS_MAXIMOS_POR_JUSTIFICACION
from .models import MovimientoAcceso


def _texto(valor):
    return ' '.join((valor or '').split())


class _GrupoConNivel(forms.ModelMultipleChoiceField):
    def label_from_instance(self, grupo):
        return str(grupo)


# ---------------------------------------------------------------------------
# Alcance de una cuenta de prefectura (Usuarios › ficha del usuario)
# ---------------------------------------------------------------------------
class AlcanceForm(EstiloCamposMixin, forms.Form):
    todo_el_colegio = forms.BooleanField(required=False, label='Todo el colegio',
                                         help_text='Solo si de verdad debe ver a todos los estudiantes: se concede expresamente.')
    niveles = forms.MultipleChoiceField(choices=NIVELES, required=False, label='Niveles completos', widget=forms.CheckboxSelectMultiple)
    grupos = _GrupoConNivel(Grupo.objects.none(), required=False, label='Grupos sueltos', widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Los grupos disponibles y los que ya tenía (aunque su grado esté oculto o de baja: no se pierden al guardar)
        conservar = [pk for pk in self.initial.get('grupos') or [] if str(pk).isdigit()]
        self.fields['grupos'].queryset = (
            Grupo.objects.filter(Q(pk__in=Grupo.objects.disponibles()) | Q(pk__in=conservar)).select_related('grado', 'nombre')
            .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre__orden', 'nombre__nombre')
        )
        self.aplicar_estilo()

    def grupos_por_nivel(self):
        """[(nombre del nivel, [(id, texto, elegido)])] para dibujar los grupos agrupados."""
        elegidos = {str(valor) for valor in (self['grupos'].value() or [])}
        nombres = dict(NIVELES)
        salida = {}
        for grupo in self.fields['grupos'].queryset:
            salida.setdefault(grupo.grado.nivel, []).append((grupo.pk, str(grupo), str(grupo.pk) in elegidos))
        return [(nombres[nivel], grupos) for nivel, grupos in salida.items()]

    def clean(self):
        datos = super().clean()
        if datos.get('todo_el_colegio'):
            datos['niveles'], datos['grupos'] = [], []
        elif datos.get('grupos') is not None and datos.get('niveles'):
            # Un grupo de un nivel ya completo sobra
            datos['grupos'] = [g for g in datos['grupos'] if g.grado.nivel not in datos['niveles']]
        return datos


# ---------------------------------------------------------------------------
# Accesos al colegio
# ---------------------------------------------------------------------------
def validar_fecha_de_clases(fecha):
    """Una fecha del ciclo actual, no futura, de lunes a viernes y que no sea un día sin clases de todo el colegio (el
    del nivel del estudiante se revisa al elegirlo)."""
    if fecha is None:
        return fecha
    if fecha > timezone.localdate():
        raise ValidationError('La fecha no puede ser futura.')
    ciclo = ciclo_actual()
    if ciclo is None or not (ciclo.fecha_inicio <= fecha <= ciclo.fecha_fin):
        raise ValidationError('La fecha debe ser del ciclo escolar actual.')
    if fecha.weekday() >= 5:
        raise ValidationError('Esa fecha es fin de semana.')
    from Alumnos.asistencias import fechas_sin_clases, niveles_sin_clases
    if fechas_sin_clases(fecha, fecha):
        raise ValidationError(f'Ese día no hubo clases ({", ".join(dict.fromkeys(niveles_sin_clases(fecha).values()))}).')
    return fecha


def validar_dia_del_nivel(alumno, fecha):
    """El mensaje si ese día no hubo clases en el nivel del estudiante (según su inscripción del ciclo actual), o None."""
    from Conducta.reglas import inscripcion_actual
    inscripcion = inscripcion_actual(alumno)
    if inscripcion is None:
        return None
    motivo = DiaNoLectivo.objects.filter(fecha=fecha, nivel=inscripcion.grado.nivel).values_list('motivo', flat=True).first()
    return f'Ese día no hubo clases en {inscripcion.grado.get_nivel_display().lower()} ({motivo}).' if motivo else None


class AccesoForm(EstiloCamposMixin, forms.Form):
    alumno = forms.ModelChoiceField(Alumno.objects.none(), widget=forms.HiddenInput,
                                    error_messages={'required': 'Busca y elige un estudiante.', 'invalid_choice': 'Elige un estudiante de tu alcance.'})
    tipo = forms.ChoiceField(choices=MovimientoAcceso.TIPOS, label='Tipo', widget=forms.RadioSelect(attrs={'class': 'choice__input'}),
                             error_messages={'required': 'Elige el tipo de registro.'})
    fecha = forms.DateField(label='Fecha', widget=FECHA, error_messages={'required': 'Indica la fecha.', 'invalid': 'Escribe una fecha válida.'})
    hora = forms.TimeField(label='Hora', widget=HORA, error_messages={'required': 'Indica la hora.', 'invalid': 'Escribe una hora válida.'})
    motivo = forms.CharField(label='Motivo', max_length=1000, widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Por qué llegó tarde, entró después o salió antes.'}),
                             error_messages={'required': 'Escribe el motivo.'})
    acompanante = forms.CharField(required=False, max_length=160, label='Quién lo acompaña o lo recoge',
                                  widget=forms.TextInput(attrs={'placeholder': 'Nombre y parentesco (si aplica)', 'autocomplete': 'off'}))
    motivo_cambio = forms.CharField(required=False, max_length=1000, label='Motivo de la corrección',
                                    widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Por qué se corrige (queda en el historial).'}))

    def __init__(self, *args, alumnos, movimiento=None, **kwargs):
        self.movimiento = movimiento
        if movimiento is not None and 'initial' not in kwargs:
            kwargs['initial'] = {'alumno': movimiento.alumno_id, 'tipo': movimiento.tipo, 'fecha': movimiento.fecha,
                                 'hora': movimiento.hora, 'motivo': movimiento.motivo, 'acompanante': movimiento.acompanante}
        super().__init__(*args, **kwargs)
        self.fields['alumno'].queryset = alumnos.exclude(estatus='BAJA')
        if movimiento is not None:
            del self.fields['alumno']
            self.fields['motivo_cambio'].required = True
            self.fields['motivo_cambio'].error_messages['required'] = 'Escribe por qué se corrige.'
        else:
            del self.fields['motivo_cambio']
        self.aplicar_estilo()

    def clean_fecha(self):
        return validar_fecha_de_clases(self.cleaned_data.get('fecha'))

    def clean_motivo(self):
        motivo = _texto(self.cleaned_data.get('motivo'))
        if len(motivo) < 5:
            raise ValidationError('Explica el motivo (al menos 5 caracteres).')
        return motivo

    def clean_acompanante(self):
        return _texto(self.cleaned_data.get('acompanante'))

    def clean_motivo_cambio(self):
        motivo = _texto(self.cleaned_data.get('motivo_cambio'))
        if len(motivo) < 5:
            raise ValidationError('Explica por qué se corrige (al menos 5 caracteres).')
        return motivo

    def clean(self):
        datos = super().clean()
        from Alumnos.asistencias import suspension_vigente
        alumno = datos.get('alumno') or (self.movimiento.alumno if self.movimiento else None)
        sin_clases = validar_dia_del_nivel(alumno, datos['fecha']) if alumno and datos.get('fecha') else None
        if sin_clases:
            self.add_error('fecha', sin_clases)
        suspension = suspension_vigente(alumno, datos['fecha']) if alumno and datos.get('fecha') and not sin_clases else None
        if suspension is not None:
            self.add_error('fecha', f'Ese día el estudiante tiene una suspensión autorizada (del {suspension.fecha_inicio:%d/%m} al {suspension.fecha_fin:%d/%m}).')
        if datos.get('tipo') == MovimientoAcceso.SALIDA and not datos.get('acompanante'):
            self.add_error('acompanante', 'En una salida anticipada indica quién lo recoge (o «Sale solo, con autorización de …»).')
        return datos


class MotivoForm(forms.Form):
    """Anular un acceso o revocar una justificación: siempre con motivo."""

    motivo = forms.CharField(
        label='Motivo', min_length=10, max_length=1000,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'field__control', 'placeholder': 'Por qué (queda en el historial).'}),
        error_messages={'required': 'Escribe el motivo.', 'min_length': 'Explica el motivo (al menos 10 caracteres).'},
    )

    def clean_motivo(self):
        return _texto(self.cleaned_data.get('motivo'))


# ---------------------------------------------------------------------------
# Justificar faltas y retardos
# ---------------------------------------------------------------------------
FOTOS = '.jpg,.jpeg,.png,.webp'


class JustificarForm(EstiloCamposMixin, forms.Form):
    ESTADOS = [('FALTA', 'Faltas'), ('RETARDO', 'Retardos')]

    alumno = forms.ModelChoiceField(Alumno.objects.none(), widget=forms.HiddenInput,
                                    error_messages={'required': 'Busca y elige un estudiante.', 'invalid_choice': 'Elige un estudiante de tu alcance.'})
    desde = forms.DateField(label='Desde', widget=FECHA, error_messages={'required': 'Indica desde qué día.', 'invalid': 'Escribe una fecha válida.'})
    hasta = forms.DateField(label='Hasta', widget=FECHA, error_messages={'required': 'Indica hasta qué día.', 'invalid': 'Escribe una fecha válida.'})
    estados = forms.MultipleChoiceField(choices=ESTADOS, initial=['FALTA'], label='Qué justificar', widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
                                        error_messages={'required': 'Elige si justificas faltas, retardos o ambos.'})
    con_entrada = forms.BooleanField(required=False, initial=True, label='Incluir la entrada al colegio (no solo las materias)')
    motivo = forms.CharField(label='Motivo', max_length=2000, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Por qué faltó o llegó tarde (receta, cita médica, trámite…).'}),
                             error_messages={'required': 'Escribe el motivo.'})
    confirmados = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, alumnos, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['alumno'].queryset = alumnos.exclude(estatus='BAJA')
        self.aplicar_estilo()
        self.fields['con_entrada'].widget.attrs['class'] = 'choice__input'

    def clean_motivo(self):
        motivo = _texto(self.cleaned_data.get('motivo'))
        if len(motivo) < 10:
            raise ValidationError('Explica el motivo (al menos 10 caracteres).')
        return motivo

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get('desde'), datos.get('hasta')
        if desde and hasta:
            hoy, ciclo = timezone.localdate(), ciclo_actual()
            if desde > hasta:
                self.add_error('hasta', 'La fecha final no puede ser anterior a la inicial.')
            elif hasta > hoy:
                self.add_error('hasta', 'No se justifica por adelantado: la fecha final no puede ser futura.')
            elif ciclo is None or desde < ciclo.fecha_inicio or hasta > ciclo.fecha_fin:
                self.add_error('desde', 'Las fechas deben ser del ciclo escolar actual.')
            elif (hasta - desde).days + 1 > DIAS_MAXIMOS_POR_JUSTIFICACION:
                self.add_error('hasta', f'Justifica como máximo {DIAS_MAXIMOS_POR_JUSTIFICACION} días a la vez.')
        archivo = self.files.get('comprobante') if self.files else None
        datos['comprobante'] = None
        if not archivo:
            self.add_error(None, 'Adjunta la foto del comprobante: es obligatoria.')
        else:
            try:
                tipo = validar_archivo(archivo)
            except ValidationError as error:
                self.add_error(None, error)
            else:
                if not tipo.startswith('image/'):
                    self.add_error(None, 'El comprobante debe ser una fotografía (JPG, PNG o WEBP).')
                else:
                    datos['comprobante'] = archivo
        datos['confirmados'] = [c for c in (datos.get('confirmados') or '').split(',') if c]
        if not datos['confirmados'] and not self.errors:
            self.add_error(None, 'Revisa la lista de registros que se justificarán y confírmala.')
        return datos


# ---------------------------------------------------------------------------
# Filtros de las listas
# ---------------------------------------------------------------------------
class _FiltroDelAlcance(forms.Form):
    """Nivel, grado, grupo y búsqueda del estudiante, limitados al alcance."""

    q = forms.CharField(required=False, label='Estudiante', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre o número de control…', 'autocomplete': 'off'}))
    nivel = forms.ChoiceField(choices=[('', 'Todos los niveles')], required=False, label='Nivel')
    grado = forms.ModelChoiceField(Grado.objects.none(), required=False, empty_label='Todos los grados', label='Grado')
    grupo = forms.ModelChoiceField(Grupo.objects.none(), required=False, empty_label='Todos los grupos', label='Grupo')

    def _preparar(self, alcance):
        grupos = alcance.grupos_visibles()
        self.fields['grupo'].queryset = grupos
        self.fields['grado'].queryset = Grado.objects.academicos().filter(pk__in=grupos.values('grado'))
        self.fields['nivel'].choices = [('', 'Todos los niveles' if alcance.total else 'Todos mis niveles'), *alcance.niveles_visibles()]

    def datos(self):
        self.is_valid()
        return {k: v for k, v in (getattr(self, 'cleaned_data', None) or {}).items() if k not in self.errors}

    def filtrar_inscripciones(self, consulta, prefijo=''):
        """Aplica nivel, grado, grupo y búsqueda a algo con inscripción (`prefijo` es el camino a ella)."""
        datos = self.datos()
        if datos.get('nivel'):
            consulta = consulta.filter(**{f'{prefijo}grado__nivel': datos['nivel']})
        if datos.get('grupo'):
            consulta = consulta.filter(**{f'{prefijo}grupo': datos['grupo']})
        elif datos.get('grado'):
            consulta = consulta.filter(**{f'{prefijo}grado': datos['grado']})
        for palabra in (datos.get('q') or '').split():
            alumno = f'{prefijo}alumno__'
            consulta = consulta.filter(
                Q(**{f'{alumno}nombre__icontains': palabra}) | Q(**{f'{alumno}apellido_paterno__icontains': palabra})
                | Q(**{f'{alumno}apellido_materno__icontains': palabra}) | Q(**{f'{alumno}referencia__icontains': palabra})
            )
        return consulta

    @property
    def activos(self):
        return sum(1 for clave, valor in self.datos().items() if valor and clave not in ('q', 'nivel', 'grupo'))


class FiltroEstudiantesForm(EstiloCamposMixin, _FiltroDelAlcance):
    def __init__(self, *args, alcance, **kwargs):
        super().__init__(*args, **kwargs)
        self._preparar(alcance)
        self.aplicar_estilo()


class FiltroAsistenciaForm(EstiloCamposMixin, _FiltroDelAlcance):
    FUENTES = [('materias', 'Por materia (pase de lista)'), ('entrada', 'Entrada al colegio')]
    # «Entraron y faltaron»: faltas del pase de lista de quien sí registró su entrada (solo por materia; 2026-10-27)
    ESTADOS = [('', 'Faltas y retardos'), ('FALTA', 'Faltas'), ('RETARDO', 'Retardos'), ('PRESENTE', 'Presentes'), ('todos', 'Todos'),
               ('ENTRARON', 'Entraron y faltaron a clases')]
    JUSTIFICACION = [('', 'Justificadas o no'), ('no', 'Sin justificar'), ('si', 'Justificadas')]
    VISTAS = [('registros', 'Cada registro'), ('estudiantes', 'Por estudiante')]

    fuente = forms.ChoiceField(choices=FUENTES, required=False, label='Asistencia')
    vista = forms.ChoiceField(choices=VISTAS, required=False, label='Ver')
    estado = forms.ChoiceField(choices=ESTADOS, required=False, label='Estado')
    justificacion = forms.ChoiceField(choices=JUSTIFICACION, required=False, label='Justificación')
    materia = forms.ModelChoiceField(MateriaGrado.objects.none(), required=False, empty_label='Todas las materias', label='Materia')
    periodo = forms.ModelChoiceField(Periodo.objects.none(), required=False, empty_label='Cualquier periodo', label='Periodo')
    desde = forms.DateField(required=False, label='Desde', widget=FECHA)
    hasta = forms.DateField(required=False, label='Hasta', widget=FECHA)

    def __init__(self, *args, alcance, **kwargs):
        super().__init__(*args, **kwargs)
        self._preparar(alcance)
        ciclo = ciclo_actual()
        niveles = [clave for clave, _ in alcance.niveles_visibles()]
        self.fields['periodo'].queryset = Periodo.objects.filter(ciclo=ciclo, nivel__in=niveles).order_by(orden_de_nivel('nivel'), 'fecha_inicio') if ciclo else Periodo.objects.none()
        self.fields['periodo'].label_from_instance = lambda p: f'{p.nombre} · {p.get_nivel_display()}'
        materias = MateriaGrado.objects.filter(ciclo=ciclo, activa=True, grupo__in=alcance.grupos_visibles()) if ciclo else MateriaGrado.objects.none()
        self.fields['materia'].queryset = materias.select_related('materia', 'grupo__grado', 'grupo__nombre').order_by(
            orden_de_nivel('grado__nivel'), 'grado__numero', 'grupo__nombre__orden', 'materia__nombre')
        self.fields['materia'].label_from_instance = lambda m: f'{m.materia} · {m.grupo}'
        self.aplicar_estilo()

    def rango(self):
        """(desde, hasta): el periodo cruzado con las fechas; sin nada, hoy."""
        datos = self.datos()
        desde, hasta = datos.get('desde'), datos.get('hasta')
        periodo = datos.get('periodo')
        if periodo is not None:
            desde = max(filter(None, (desde, periodo.fecha_inicio)))
            hasta = min(filter(None, (hasta, periodo.fecha_fin)))
        if desde is None and hasta is None:
            hoy = timezone.localdate()
            return hoy, hoy
        return desde, hasta

    @property
    def activos(self):
        return sum(1 for clave, valor in self.datos().items()
                   if valor and clave in ('materia', 'periodo', 'grado', 'justificacion'))


class FiltroAccesosForm(EstiloCamposMixin, _FiltroDelAlcance):
    REGISTROS = [('vigentes', 'Vigentes'), ('anulados', 'Anulados'), ('todos', 'Vigentes y anulados')]

    tipo = forms.ChoiceField(choices=[('', 'Todos los tipos'), *MovimientoAcceso.TIPOS], required=False, label='Tipo')
    desde = forms.DateField(required=False, label='Desde', widget=FECHA)
    hasta = forms.DateField(required=False, label='Hasta', widget=FECHA)
    registros = forms.ChoiceField(choices=REGISTROS, required=False, label='Registros')

    def __init__(self, *args, alcance, **kwargs):
        super().__init__(*args, **kwargs)
        self._preparar(alcance)
        self.aplicar_estilo()


def fecha_de(texto):
    try:
        return date.fromisoformat(texto) if texto else None
    except (TypeError, ValueError):
        return None


TAMANO_MAXIMO = TAMANO_MAXIMO_MB
