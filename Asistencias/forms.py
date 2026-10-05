from datetime import date, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from Alumnos.asistencias import ciclo_de_fecha, dias_de_clases
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import (
    Alumno,
    AsistenciaGeneral,
    CicloEscolar,
    ConfiguracionAsistencia,
    DiaNoLectivo,
    Grado,
    Inscripcion,
    Justificacion,
    MateriaGrado,
    Profesor,
)

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
HORA = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')

# Comprobantes que se aceptan y tamaño máximo (en MB)
EXTENSIONES_COMPROBANTE = ('pdf', 'jpg', 'jpeg', 'png', 'webp')
TAMANO_MAXIMO_MB = 5
DIAS_MAXIMOS_JUSTIFICACION = 60
DIAS_MAXIMOS_SIN_CLASES = 120


def _activos(formulario):
    """Valores válidos de los filtros (los inválidos de la URL se ignoran)."""
    formulario.is_valid()
    return {k: v for k, v in getattr(formulario, 'cleaned_data', {}).items() if v}


# ---------------------------------------------------------------------------
# Asistencia general del día
# ---------------------------------------------------------------------------
class AsistenciaDiaForm(forms.Form):
    """Captura manual de la asistencia general de un alumno en un día (ventana de la pantalla del día)."""

    inscripcion = forms.IntegerField()
    fecha = forms.DateField(input_formats=['%Y-%m-%d'])
    estado = forms.ChoiceField(choices=AsistenciaGeneral.ESTADO_CHOICES, error_messages={'invalid_choice': 'Elige presente, retardo o falta.'})
    hora = forms.TimeField(required=False, error_messages={'invalid': 'Escribe una hora válida.'})
    observaciones = forms.CharField(required=False, max_length=250)
    propagar = forms.BooleanField(required=False)

    def clean_observaciones(self):
        return ' '.join(self.cleaned_data.get('observaciones', '').split())


class FiltroDiaForm(EstiloCamposMixin, forms.Form):
    ESTADO_CHOICES = [
        ('', 'Todos los estados'),
        ('PRESENTE', 'Presentes'),
        ('RETARDO', 'Con retardo'),
        ('FALTA', 'Faltas'),
        ('SIN_REGISTRO', 'Sin entrada'),
    ]

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre o referencia…', 'autocomplete': 'off',
    }))
    grado = forms.ModelChoiceField(Grado.objects.none(), required=False, empty_label='Todos los grados', label='Grado')
    estado = forms.ChoiceField(required=False, choices=ESTADO_CHOICES, label='Estado')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['grado'].queryset = Grado.objects.academicos()
        self.aplicar_estilo()

    @property
    def activos(self):
        return _activos(self)


# ---------------------------------------------------------------------------
# Pase de lista
# ---------------------------------------------------------------------------
class FiltroClasesForm(EstiloCamposMixin, forms.Form):
    profesor = forms.ModelChoiceField(Profesor.objects.none(), required=False, empty_label='Todos los profesores', label='Profesor')
    grado = forms.ModelChoiceField(Grado.objects.none(), required=False, empty_label='Todos los grados', label='Grado')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['profesor'].queryset = Profesor.objects.filter(estatus='ACTIVO')
        self.fields['grado'].queryset = Grado.objects.academicos()
        self.aplicar_estilo()

    @property
    def activos(self):
        return _activos(self)


# ---------------------------------------------------------------------------
# Justificaciones
# ---------------------------------------------------------------------------
MODOS_MATERIAS = [
    ('NINGUNA', 'Ninguna'),
    ('TODAS', 'Todas las materias del día'),
    ('ALGUNAS', 'Solo algunas materias'),
]


class MateriasDelGradoField(forms.ModelMultipleChoiceField):
    """Casillas de las materias de un grado: solo el nombre de la materia (el grado y el ciclo ya se saben)."""

    def label_from_instance(self, asignacion):
        return asignacion.materia.nombre


def _validar_comprobante(archivo):
    if not archivo:
        return archivo
    extension = archivo.name.rsplit('.', 1)[-1].lower() if '.' in archivo.name else ''
    if extension not in EXTENSIONES_COMPROBANTE:
        raise ValidationError('El comprobante debe ser un PDF o una imagen (JPG, PNG o WEBP).')
    if archivo.size > TAMANO_MAXIMO_MB * 1024 * 1024:
        raise ValidationError(f'El comprobante no debe pasar de {TAMANO_MAXIMO_MB} MB.')
    return archivo


def _materias_de(inscripcion):
    """Materias vigentes del grado del alumno en el ciclo de su inscripción."""
    return (
        MateriaGrado.objects.filter(ciclo=inscripcion.ciclo, grado=inscripcion.grado, activa=True, materia__activa=True)
        .select_related('materia').order_by('materia__nombre')
    )


class _AlcanceMixin:
    """Qué se justifica: la falta general, todas las materias o solo algunas (o combinaciones)."""

    def _validar_alcance(self, datos):
        general, modo, materias = datos.get('justifica_general'), datos.get('materias_modo'), datos.get('materias')
        if not general and modo == 'NINGUNA':
            self.add_error('materias_modo', 'Elige qué se justifica: la falta general, las materias o ambas.')
        elif modo == 'ALGUNAS' and not materias:
            self.add_error('materias', 'Elige al menos una materia.')


class JustificacionForm(_AlcanceMixin, EstiloCamposMixin, forms.Form):
    """Alta de una justificación para un día o para varios días seguidos."""

    alumno = forms.ModelChoiceField(
        Alumno.objects.exclude(estatus='BAJA'), widget=forms.HiddenInput,
        error_messages={'required': 'Busca y elige un alumno.', 'invalid_choice': 'Elige un alumno de la lista.'},
    )
    fecha_desde = forms.DateField(label='Fecha', widget=FECHA, error_messages={'required': 'Indica la fecha.', 'invalid': 'Escribe una fecha válida.'})
    fecha_hasta = forms.DateField(
        required=False, label='Hasta (opcional)', widget=FECHA, error_messages={'invalid': 'Escribe una fecha válida.'},
        help_text='Para justificar varios días seguidos. Solo se justifican los días de clases.',
    )
    justifica_general = forms.BooleanField(
        required=False, initial=True, label='La falta general del día (no entró al colegio)', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}),
    )
    materias_modo = forms.ChoiceField(choices=MODOS_MATERIAS, initial='TODAS', widget=forms.RadioSelect(attrs={'class': 'choice__input'}), label='Faltas por materia que se justifican')
    materias = MateriasDelGradoField(
        MateriaGrado.objects.none(), required=False, widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}), label='Materias',
        error_messages={'invalid_choice': 'Elige materias del grado del alumno.', 'invalid_pk_value': 'Elige materias del grado del alumno.'},
    )
    motivo = forms.CharField(
        label='Motivo', max_length=1000, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Cita médica, enfermedad, trámite familiar…'}),
        error_messages={'required': 'Escribe el motivo de la justificación.'},
    )
    documento = forms.FileField(
        required=False, label='Comprobante', widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png,.webp'}),
        help_text=f'Opcional. PDF o imagen de hasta {TAMANO_MAXIMO_MB} MB.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()
        # Las materias que se ofrecen son las del grado del alumno (si ya se sabe quién es y de qué día se trata)
        datos = self.data if self.is_bound else self.initial
        self.inscripcion_previa = self._inscripcion_de(datos.get('alumno'), datos.get('fecha_desde'))
        if self.inscripcion_previa:
            self.fields['materias'].queryset = _materias_de(self.inscripcion_previa)

    @staticmethod
    def _inscripcion_de(alumno, fecha):
        if not str(alumno or '').isdigit():
            return None
        try:
            fecha = date.fromisoformat(str(fecha)) if fecha else timezone.localdate()
        except ValueError:
            fecha = timezone.localdate()
        ciclo = ciclo_de_fecha(fecha) or CicloEscolar.objects.filter(activo=True).first()
        if ciclo is None:
            return None
        return Inscripcion.objects.filter(alumno_id=alumno, ciclo=ciclo, activa=True).select_related('grado', 'ciclo', 'alumno').first()

    def clean_documento(self):
        return _validar_comprobante(self.cleaned_data.get('documento'))

    def clean_motivo(self):
        return ' '.join(self.cleaned_data.get('motivo', '').split())

    def clean(self):
        datos = super().clean()
        alumno, desde, hasta = datos.get('alumno'), datos.get('fecha_desde'), datos.get('fecha_hasta')
        self._validar_alcance(datos)
        if not (alumno and desde):
            return datos

        ciclo = ciclo_de_fecha(desde)
        if ciclo is None:
            self.add_error('fecha_desde', 'Esa fecha queda fuera de las fechas de cualquier ciclo escolar.')
            return datos
        if not ciclo.activo:
            self.add_error('fecha_desde', f'El ciclo {ciclo} no es el ciclo actual: sus justificaciones ya no se modifican.')
            return datos
        inscripcion = Inscripcion.objects.filter(alumno=alumno, ciclo=ciclo, activa=True).select_related('grado', 'ciclo').first()
        if inscripcion is None:
            self.add_error('alumno', f'{alumno} no tiene una inscripción vigente en el ciclo {ciclo}.')
            return datos

        hasta = hasta or desde
        if hasta < desde:
            self.add_error('fecha_hasta', 'La fecha final no puede ser anterior a la inicial.')
            return datos
        if hasta > ciclo.fecha_fin:
            self.add_error('fecha_hasta', f'El rango debe terminar dentro del ciclo {ciclo} (hasta el {ciclo.fecha_fin:%d/%m/%Y}).')
            return datos
        if (hasta - desde).days >= DIAS_MAXIMOS_JUSTIFICACION:
            self.add_error('fecha_hasta', f'Justifica como máximo {DIAS_MAXIMOS_JUSTIFICACION} días a la vez.')
            return datos

        fechas = dias_de_clases(desde, hasta, ciclo)
        if not fechas:
            self.add_error('fecha_desde', 'Ese día no es de clases (fin de semana o día sin clases).' if desde == hasta else 'Ningún día de ese rango es de clases.')
            return datos

        ya_justificadas = set(
            Justificacion.objects.filter(inscripcion=inscripcion, fecha__in=fechas, activa=True).values_list('fecha', flat=True)
        )
        if desde == hasta and ya_justificadas:
            self.add_error('fecha_desde', 'Ese día ya tiene una justificación vigente. Edítala desde la lista de justificaciones.')
            return datos
        if ya_justificadas and len(ya_justificadas) == len(fechas):
            self.add_error('fecha_hasta', 'Todos esos días ya tienen una justificación vigente.')
            return datos

        datos['inscripcion'] = inscripcion
        datos['fechas'] = [fecha for fecha in fechas if fecha not in ya_justificadas]
        datos['omitidas'] = sorted(ya_justificadas)
        return datos


class JustificacionEdicionForm(_AlcanceMixin, EstiloCamposMixin, forms.Form):
    """Cambia qué cubre una justificación, su motivo o su comprobante (el alumno y el día no cambian)."""

    justifica_general = forms.BooleanField(
        required=False, label='La falta general del día (no entró al colegio)', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}),
    )
    materias_modo = forms.ChoiceField(choices=MODOS_MATERIAS, widget=forms.RadioSelect(attrs={'class': 'choice__input'}), label='Faltas por materia que se justifican')
    materias = MateriasDelGradoField(
        MateriaGrado.objects.none(), required=False, widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}), label='Materias',
        error_messages={'invalid_choice': 'Elige materias del grado del alumno.', 'invalid_pk_value': 'Elige materias del grado del alumno.'},
    )
    motivo = forms.CharField(
        label='Motivo', max_length=1000, widget=forms.Textarea(attrs={'rows': 3}),
        error_messages={'required': 'Escribe el motivo de la justificación.'},
    )
    documento = forms.FileField(
        required=False, label='Reemplazar comprobante', widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png,.webp'}),
        help_text=f'Opcional. PDF o imagen de hasta {TAMANO_MAXIMO_MB} MB.',
    )
    quitar_documento = forms.BooleanField(required=False, label='Quitar el comprobante actual', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))

    def __init__(self, *args, justificacion, **kwargs):
        self.justificacion = justificacion
        if 'initial' not in kwargs and not args:
            kwargs['initial'] = {
                'justifica_general': justificacion.justifica_general,
                'materias_modo': 'TODAS' if justificacion.todas_materias else ('ALGUNAS' if justificacion.pk and justificacion.materias.exists() else 'NINGUNA'),
                'materias': list(justificacion.materias.values_list('pk', flat=True)) if justificacion.pk else [],
                'motivo': justificacion.motivo,
            }
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()
        self.fields['materias'].queryset = _materias_de(justificacion.inscripcion)

    def clean_documento(self):
        return _validar_comprobante(self.cleaned_data.get('documento'))

    def clean_motivo(self):
        return ' '.join(self.cleaned_data.get('motivo', '').split())

    def clean(self):
        datos = super().clean()
        self._validar_alcance(datos)
        return datos


class FiltroJustificacionesForm(EstiloCamposMixin, forms.Form):
    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Alumno, referencia o motivo…', 'autocomplete': 'off',
    }))
    grado = forms.ModelChoiceField(Grado.objects.none(), required=False, empty_label='Todos los grados', label='Grado')
    desde = forms.DateField(required=False, label='Desde', widget=FECHA)
    hasta = forms.DateField(required=False, label='Hasta', widget=FECHA)
    estado = forms.ChoiceField(required=False, choices=[('', 'Vigentes'), ('ANULADA', 'Anuladas')], label='Estado')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['grado'].queryset = Grado.objects.academicos()
        self.aplicar_estilo()

    @property
    def activos(self):
        return _activos(self)

    def filtrar(self, queryset, con_estado=True):
        datos = self.activos
        for palabra in datos.get('q', '').split():
            queryset = queryset.filter(
                Q(inscripcion__alumno__nombre__icontains=palabra)
                | Q(inscripcion__alumno__apellido_paterno__icontains=palabra)
                | Q(inscripcion__alumno__apellido_materno__icontains=palabra)
                | Q(inscripcion__alumno__referencia__icontains=palabra)
                | Q(motivo__icontains=palabra)
            )
        if datos.get('grado'):
            queryset = queryset.filter(inscripcion__grado=datos['grado'])
        if datos.get('desde'):
            queryset = queryset.filter(fecha__gte=datos['desde'])
        if datos.get('hasta'):
            queryset = queryset.filter(fecha__lte=datos['hasta'])
        if con_estado:
            queryset = queryset.filter(activa=datos.get('estado') != 'ANULADA')
        return queryset


# ---------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------
UMBRAL_ASISTENCIA = 85  # por debajo de este porcentaje el reporte marca al alumno


class FiltroReporteForm(EstiloCamposMixin, forms.Form):
    """Qué reporte se pide. `resolver()` completa lo que falte (ciclo actual, mes en curso) y valida el rango."""

    VISTAS = [('resumen', 'Resumen por alumno'), ('cuadricula', 'Cuadrícula por día')]

    ciclo = forms.ModelChoiceField(CicloEscolar.objects.all(), required=False, empty_label=None, label='Ciclo escolar')
    grado = forms.ModelChoiceField(Grado.objects.none(), required=False, empty_label='Elige un grado', label='Grado')
    materia = forms.IntegerField(required=False, widget=forms.HiddenInput)
    desde = forms.DateField(required=False, label='Desde', widget=FECHA)
    hasta = forms.DateField(required=False, label='Hasta', widget=FECHA)
    vista = forms.ChoiceField(required=False, choices=VISTAS, label='Vista')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['grado'].queryset = Grado.objects.academicos()
        self.aplicar_estilo()

    def resolver(self):
        """(ciclo, grado, asignacion, desde, hasta, vista). `asignacion` es la materia del grado si se pidió una."""
        self.is_valid()
        datos = getattr(self, 'cleaned_data', {})
        ciclo = datos.get('ciclo') or CicloEscolar.objects.filter(activo=True).first() or CicloEscolar.objects.first()
        grado = datos.get('grado')
        hoy = timezone.localdate()
        desde = datos.get('desde') or hoy.replace(day=1)
        hasta = datos.get('hasta') or hoy
        if ciclo:
            desde, hasta = max(desde, ciclo.fecha_inicio), min(hasta, ciclo.fecha_fin)
            if desde > hasta:           # el mes en curso queda fuera del ciclo: se muestra el ciclo completo
                desde, hasta = ciclo.fecha_inicio, min(hoy, ciclo.fecha_fin)
        asignacion = None
        if ciclo and grado and datos.get('materia'):
            asignacion = MateriaGrado.objects.filter(pk=datos['materia'], ciclo=ciclo, grado=grado).select_related('materia').first()
        return ciclo, grado, asignacion, desde, hasta, datos.get('vista') or 'resumen'


# ---------------------------------------------------------------------------
# Ajustes
# ---------------------------------------------------------------------------
class ConfiguracionForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = ConfiguracionAsistencia
        fields = ['hora_entrada', 'tolerancia_minutos', 'cierre_automatico']
        widgets = {
            'hora_entrada': HORA,
            'tolerancia_minutos': forms.NumberInput(attrs={'min': 0, 'max': 120, 'inputmode': 'numeric'}),
            'cierre_automatico': forms.CheckboxInput(),
        }
        help_texts = {
            'hora_entrada': 'Quien registra su entrada después de esta hora más la tolerancia queda con retardo.',
            'tolerancia_minutos': 'Minutos de gracia después de la hora de entrada y del inicio de cada clase.',
            'cierre_automatico': 'Con la primera entrada de la mañana se generan las faltas de los días anteriores que sigan abiertos.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()


class DiaNoLectivoForm(EstiloCamposMixin, forms.Form):
    """Un día sin clases o un periodo (vacaciones, suspensión)."""

    desde = forms.DateField(label='Fecha', widget=FECHA, error_messages={'required': 'Indica la fecha.', 'invalid': 'Escribe una fecha válida.'})
    hasta = forms.DateField(required=False, label='Hasta (opcional)', widget=FECHA, error_messages={'invalid': 'Escribe una fecha válida.'},
                            help_text='Para un periodo, por ejemplo vacaciones.')
    motivo = forms.CharField(label='Motivo', max_length=120, widget=forms.TextInput(attrs={'placeholder': 'Consejo técnico, vacaciones, puente…'}),
                             error_messages={'required': 'Escribe el motivo.'})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_motivo(self):
        return ' '.join(self.cleaned_data.get('motivo', '').split())

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get('desde'), datos.get('hasta')
        if not desde:
            return datos
        hasta = hasta or desde
        if hasta < desde:
            self.add_error('hasta', 'La fecha final no puede ser anterior a la inicial.')
        elif (hasta - desde).days >= DIAS_MAXIMOS_SIN_CLASES:
            self.add_error('hasta', f'Registra como máximo {DIAS_MAXIMOS_SIN_CLASES} días a la vez.')
        else:
            existentes = set(DiaNoLectivo.objects.filter(fecha__range=(desde, hasta)).values_list('fecha', flat=True))
            todos = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
            nuevos = [fecha for fecha in todos if fecha not in existentes]
            if not nuevos:
                self.add_error('desde', 'Ese día ya está registrado como día sin clases.' if desde == hasta else 'Todos esos días ya están registrados.')
            datos['fechas'] = nuevos
        return datos
