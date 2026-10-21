"""Formularios de las reuniones con familias. Validan formatos y opciones; las reglas (acompañante directivo, cruces de
horario, estados) están en Reuniones/reglas.py, que vuelve a revisar todo."""
from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from Alumnos.academico import ciclo_actual
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Grupo, MateriaGrado, TutorAlumno
from Conducta.forms import ACEPTA, TAMANO_MAXIMO_MB

from .alcance import ACOMPANAR, GESTIONAR, PARTICIPAR, REGISTRAR, TODO, candidatos_a_acompanar, cuentas_con_permiso
from .disponibilidad import nombre_de_persona
from .models import DIAS, Acuerdo, AdjuntoReunion, ConfiguracionReuniones, ContactoReunion, MotivoReunion, Reunion, SalaReunion

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
HORA = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')
CASILLA = {'class': 'choice__input'}
PROPUESTAS = 3
AYUDA_DE_ARCHIVOS = f'Fotos (JPG, PNG o WEBP) o PDF, de {TAMANO_MAXIMO_MB} MB como máximo cada uno.'
__all__ = ['ACEPTA', 'AYUDA_DE_ARCHIVOS']


def nombre_de_cuenta(usuario):
    return usuario.get_full_name() or usuario.get_username()


def _rol(usuario):
    from Usuarios.seguridad import rol_de
    rol = rol_de(usuario)
    return rol.grupo.name if rol else ''


class CampoDeCuentas(forms.ModelMultipleChoiceField):
    def label_from_instance(self, usuario):
        rol = _rol(usuario)
        return f'{nombre_de_cuenta(usuario)} · {rol}' if rol else nombre_de_cuenta(usuario)


class CampoDeCuenta(forms.ModelChoiceField):
    def label_from_instance(self, usuario):
        rol = _rol(usuario)
        return f'{nombre_de_cuenta(usuario)} · {rol}' if rol else nombre_de_cuenta(usuario)


class CampoDeDocentes(forms.ModelMultipleChoiceField):
    """Cada docente con lo que imparte a los grupos de los estudiantes (si les da clase)."""

    def __init__(self, *args, materias=None, **kwargs):
        self.materias = materias or {}
        super().__init__(*args, **kwargs)

    def label_from_instance(self, usuario):
        materias = self.materias.get(usuario.pk)
        return f'{nombre_de_cuenta(usuario)} · {materias}' if materias else nombre_de_cuenta(usuario)


class CampoDeTutores(forms.ModelMultipleChoiceField):
    def label_from_instance(self, tutor):
        return nombre_de_persona(tutor)


def docentes_con_cuenta():
    """Las cuentas activas de los profesores activos (para elegir a los docentes de una reunión)."""
    return get_user_model().objects.filter(is_active=True, profesor__estatus='ACTIVO').order_by('first_name', 'last_name', 'username')


def materias_por_docente(grupos):
    """{id de cuenta: «Matemáticas (2° A) · Español (2° A)»} de los docentes que dan clase a esos grupos este ciclo."""
    ciclo = ciclo_actual()
    if ciclo is None or not grupos:
        return {}
    textos = {}
    for clase in (MateriaGrado.objects.filter(ciclo=ciclo, activa=True, grupo__in=grupos, profesor__usuario__isnull=False)
                  .select_related('materia', 'grupo__grado', 'grupo__nombre', 'profesor')):
        textos.setdefault(clase.profesor.usuario_id, []).append(f'{clase.materia.nombre} ({clase.grupo.corto})')
    return {usuario: ' · '.join(sorted(set(materias))) for usuario, materias in textos.items()}


def cuentas_del_modulo():
    """Las cuentas que pueden participar o atender reuniones (para el personal y el responsable)."""
    ids = set()
    for permiso in (PARTICIPAR, REGISTRAR, GESTIONAR, ACOMPANAR, TODO):
        ids |= set(cuentas_con_permiso(permiso).values_list('pk', flat=True))
    return get_user_model().objects.filter(pk__in=ids).order_by('first_name', 'last_name', 'username')


def _ordenar_docentes(consulta, materias):
    """Primero quienes dan clase a los estudiantes."""
    docentes = list(consulta)
    docentes.sort(key=lambda u: (u.pk not in materias, nombre_de_cuenta(u).lower()))
    return docentes


# ---------------------------------------------------------------------------
# Registro de la solicitud
# ---------------------------------------------------------------------------
class BuscarTutorForm(EstiloCamposMixin, forms.Form):
    q = forms.CharField(required=False, label='Buscar al tutor', max_length=80, widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre, apellido o teléfono del tutor, o nombre del estudiante…', 'autocomplete': 'off',
        'autofocus': True}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()


class SolicitudForm(EstiloCamposMixin, forms.Form):
    alumnos = forms.MultipleChoiceField(label='Estudiantes', widget=forms.CheckboxSelectMultiple(attrs=CASILLA))
    otros_tutores = CampoDeTutores(queryset=None, required=False, label='Otros tutores que asistirán',
                                   widget=forms.CheckboxSelectMultiple(attrs=CASILLA))
    telefono = forms.CharField(label='Teléfono de contacto', max_length=20)
    telefono_verificado = forms.BooleanField(required=False, label='Verifiqué el teléfono en la llamada',
                                             widget=forms.CheckboxInput(attrs=CASILLA))
    area = forms.ChoiceField(label='Quiere reunirse con', choices=[('', 'Elige con quién'), *Reunion.AREAS])
    docentes = CampoDeDocentes(queryset=None, required=False, label='Docentes involucrados',
                               widget=forms.CheckboxSelectMultiple(attrs={**CASILLA, 'data-reuniones-docente': ''}),
                               help_text='Primero, quienes dan clase a los estudiantes.')
    acompanante = CampoDeCuenta(queryset=None, required=False, label='Acompañante directivo', empty_label='Elige al acompañante',
                                help_text='Dirección, coordinación académica o prefectura de estos niveles. Obligatorio si participa un docente.')
    acompanante_despues = forms.BooleanField(required=False, label='Guardar pendiente: asignaré al acompañante después',
                                             widget=forms.CheckboxInput(attrs=CASILLA))
    responsable = CampoDeCuenta(queryset=None, required=False, label='Responsable de la reunión', empty_label='Asignar después',
                                help_text='Si no eliges a nadie y hay acompañante, queda como responsable.')
    motivo = forms.ModelChoiceField(MotivoReunion.objects.none(), label='Motivo', empty_label='Elige el motivo')
    prioridad = forms.ChoiceField(label='Prioridad', choices=Reunion.PRIORIDADES, initial=Reunion.NORMAL)
    descripcion = forms.CharField(label='Descripción de la solicitud', max_length=2000,
                                  widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Lo que comentó el tutor en la llamada'}))
    observaciones = forms.CharField(label='Observaciones internas', max_length=2000, required=False,
                                    widget=forms.Textarea(attrs={'rows': 2}), help_text='Solo para el personal: el tutor nunca las ve.')

    def __init__(self, *args, tutor, **kwargs):
        super().__init__(*args, **kwargs)
        self.tutor = tutor
        vinculos = (TutorAlumno.objects.filter(tutor=tutor, activo=True, alumno__estatus='ACTIVO')
                    .select_related('alumno').order_by('alumno__nombre'))
        from .reglas import inscripcion_vigente
        self.estudiantes = []
        for vinculo in vinculos:
            inscripcion = inscripcion_vigente(vinculo.alumno)
            self.estudiantes.append((vinculo.alumno, inscripcion))
        self.fields['alumnos'].choices = [(str(a.pk), self._etiqueta_de(a, i)) for a, i in self.estudiantes]
        if len(self.estudiantes) == 1:
            self.fields['alumnos'].initial = [str(self.estudiantes[0][0].pk)]
        alumnos = [a for a, _ in self.estudiantes]
        self.fields['otros_tutores'].queryset = (type(tutor).objects.filter(alumnos_relacionados__alumno__in=alumnos,
                                                                            alumnos_relacionados__activo=True, estatus='ACTIVO')
                                                 .exclude(pk=tutor.pk).distinct().order_by('nombre'))
        self.fields['telefono'].initial = tutor.telefono
        if tutor.telefono_alternativo:
            self.fields['telefono'].help_text = f'Alternativo: {tutor.telefono_alternativo}'
        inscripciones = [i for _, i in self.estudiantes if i]
        grupos = [i.grupo_id for i in inscripciones if i.grupo_id]
        materias = materias_por_docente(grupos)
        self.fields['docentes'].materias = materias
        self.fields['docentes'].queryset = docentes_con_cuenta()
        self.fields['docentes'].choices = [(u.pk, self.fields['docentes'].label_from_instance(u))
                                           for u in _ordenar_docentes(docentes_con_cuenta(), materias)]
        candidatos = candidatos_a_acompanar(inscripciones)
        self.fields['acompanante'].queryset = get_user_model().objects.filter(pk__in=[u.pk for u in candidatos]).order_by('first_name', 'last_name')
        self.fields['responsable'].queryset = cuentas_del_modulo()
        self.fields['motivo'].queryset = MotivoReunion.objects.filter(activo=True)
        for n in range(1, PROPUESTAS + 1):
            self.fields[f'propuesta_{n}_fecha'] = forms.DateField(required=False, label=f'Opción {n}: fecha', widget=FECHA)
            self.fields[f'propuesta_{n}_desde'] = forms.TimeField(required=False, label='Desde', widget=HORA)
            self.fields[f'propuesta_{n}_hasta'] = forms.TimeField(required=False, label='Hasta', widget=HORA)
        self.aplicar_estilo()

    @staticmethod
    def _etiqueta_de(alumno, inscripcion):
        nombre = nombre_de_persona(alumno)
        if inscripcion is None:
            return f'{nombre} · sin inscripción en el ciclo actual'
        grupo = inscripcion.grupo.corto if inscripcion.grupo_id else str(inscripcion.grado)
        return f'{nombre} · {inscripcion.grado.get_nivel_display()}, {grupo}'

    def propuestas(self):
        return [[self[f'propuesta_{n}_fecha'], self[f'propuesta_{n}_desde'], self[f'propuesta_{n}_hasta']] for n in range(1, PROPUESTAS + 1)]

    def clean(self):
        datos = super().clean()
        if datos.get('area') == Reunion.DOCENTE and not datos.get('docentes'):
            self.add_error('docentes', 'Elige al docente con quien quiere reunirse el tutor.')
        acompanante, docentes = datos.get('acompanante'), datos.get('docentes') or []
        if docentes and not acompanante and not datos.get('acompanante_despues'):
            self.add_error('acompanante', 'Toda reunión con un docente necesita un acompañante directivo. Elígelo o marca '
                                          '«asignaré al acompañante después» (la cita no se podrá confirmar sin él).')
        if acompanante is not None and acompanante in docentes:
            self.add_error('acompanante', 'El acompañante no puede ser uno de los docentes.')
        propuestas = []
        for n in range(1, PROPUESTAS + 1):
            fecha, desde, hasta = (datos.get(f'propuesta_{n}_{c}') for c in ('fecha', 'desde', 'hasta'))
            if not fecha and (desde or hasta):
                self.add_error(f'propuesta_{n}_fecha', 'Indica la fecha de esta opción.')
            elif desde and hasta and hasta <= desde:
                self.add_error(f'propuesta_{n}_hasta', 'Debe ser después de la hora inicial.')
            elif fecha:
                propuestas.append({'fecha': fecha.isoformat(), 'desde': desde.strftime('%H:%M') if desde else '',
                                   'hasta': hasta.strftime('%H:%M') if hasta else ''})
        datos['lista_de_propuestas'] = propuestas
        return datos

    def alumnos_elegidos(self):
        elegidos = set(self.cleaned_data.get('alumnos') or [])
        return [a for a, _ in self.estudiantes if str(a.pk) in elegidos]


# ---------------------------------------------------------------------------
# Participantes, programación y confirmaciones
# ---------------------------------------------------------------------------
class ParticipantesForm(EstiloCamposMixin, forms.Form):
    docentes = CampoDeDocentes(queryset=None, required=False, label='Docentes', widget=forms.CheckboxSelectMultiple(attrs={**CASILLA, 'data-reuniones-docente': ''}))
    acompanantes = CampoDeCuentas(queryset=None, required=False, label='Acompañantes directivos', widget=forms.CheckboxSelectMultiple(attrs=CASILLA),
                                  help_text='Dirección, coordinación académica o prefectura de estos niveles. Uno puede acompañar a varios docentes.')
    personal = CampoDeCuentas(queryset=None, required=False, label='Otro personal escolar', widget=forms.CheckboxSelectMultiple(attrs=CASILLA))
    responsable = CampoDeCuenta(queryset=None, required=False, label='Responsable de la reunión', empty_label='Sin asignar')
    tutores = CampoDeTutores(queryset=None, required=False, label='Tutores que asistirán', widget=forms.CheckboxSelectMultiple(attrs=CASILLA),
                             help_text='El tutor que la solicitó asiste siempre.')

    def __init__(self, *args, reunion, **kwargs):
        from .alcance import inscripciones_de
        activos = list(reunion.participantes.filter(activo=True))
        inicial = {
            'docentes': [p.usuario_id for p in activos if p.papel == 'DOCENTE'],
            'acompanantes': [p.usuario_id for p in activos if p.papel == 'ACOMPANANTE'],
            'personal': [p.usuario_id for p in activos if p.papel == 'PERSONAL' and p.usuario_id != reunion.responsable_id],
            'responsable': reunion.responsable_id,
            'tutores': list(reunion.tutores.filter(solicitante=False).values_list('tutor_id', flat=True)),
        }
        kwargs.setdefault('initial', inicial)
        super().__init__(*args, **kwargs)
        inscripciones = inscripciones_de(reunion)
        materias = materias_por_docente([i.grupo_id for i in inscripciones if i.grupo_id])
        self.fields['docentes'].materias = materias
        self.fields['docentes'].queryset = docentes_con_cuenta() | get_user_model().objects.filter(pk__in=inicial['docentes'])
        self.fields['docentes'].choices = [(u.pk, self.fields['docentes'].label_from_instance(u))
                                           for u in _ordenar_docentes(self.fields['docentes'].queryset.distinct(), materias)]
        candidatos = {u.pk for u in candidatos_a_acompanar(inscripciones)} | set(inicial['acompanantes'])
        self.fields['acompanantes'].queryset = get_user_model().objects.filter(pk__in=candidatos).order_by('first_name', 'last_name')
        modulo = cuentas_del_modulo() | get_user_model().objects.filter(pk__in=inicial['personal'] + ([reunion.responsable_id] if reunion.responsable_id else []))
        self.fields['personal'].queryset = modulo.distinct().order_by('first_name', 'last_name')
        self.fields['responsable'].queryset = modulo.distinct().order_by('first_name', 'last_name')
        alumnos = reunion.estudiantes.values('alumno')
        from Alumnos.models import Tutor
        self.fields['tutores'].queryset = (Tutor.objects.filter(alumnos_relacionados__alumno__in=alumnos, alumnos_relacionados__activo=True)
                                           .exclude(pk=reunion.tutor_id).distinct().order_by('nombre'))
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        docentes, acompanantes = list(datos.get('docentes') or []), list(datos.get('acompanantes') or [])
        if any(u in docentes for u in acompanantes):
            self.add_error('acompanantes', 'Una persona no puede ser docente y acompañante de la misma reunión.')
        return datos


class ProgramarForm(EstiloCamposMixin, forms.Form):
    fecha = forms.DateField(label='Fecha', widget=FECHA)
    hora_inicio = forms.TimeField(label='Hora de inicio', widget=HORA)
    hora_fin = forms.TimeField(label='Hora de término', widget=HORA, required=False)
    sala = forms.ModelChoiceField(SalaReunion.objects.none(), label='Lugar o sala', empty_label='Elige el lugar')

    def __init__(self, *args, reunion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.configuracion = ConfiguracionReuniones.actual()
        self.fields['sala'].queryset = SalaReunion.objects.filter(activo=True)
        self.fields['hora_fin'].help_text = f'Vacía: {self.configuracion.duracion} minutos después del inicio.'
        if reunion is not None and reunion.programada:
            self.fields['fecha'].initial = reunion.fecha
            self.fields['hora_inicio'].initial = reunion.hora_inicio
            self.fields['hora_fin'].initial = reunion.hora_fin
            self.fields['sala'].initial = reunion.sala_id
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        from .disponibilidad import hora_fin_sugerida
        if datos.get('hora_inicio') and not datos.get('hora_fin'):
            datos['hora_fin'] = hora_fin_sugerida(datos['hora_inicio'], self.configuracion.duracion)
        if datos.get('hora_inicio') and datos.get('hora_fin') and datos['hora_fin'] <= datos['hora_inicio']:
            self.add_error('hora_fin', 'Debe ser después de la hora de inicio.')
        return datos


class ReprogramarForm(ProgramarForm):
    motivo = forms.CharField(label='Motivo de la reprogramación', max_length=1000, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()


class ConfirmarTutorForm(EstiloCamposMixin, forms.Form):
    tutor = forms.ModelChoiceField(queryset=None, label='Quién confirmó', empty_label=None)
    medio = forms.ChoiceField(label='Medio', choices=[c for c in ContactoReunion.MEDIOS if c[0] != 'PORTAL'], initial='TELEFONO')
    recibio = CampoDeCuenta(queryset=None, label='Quién recibió la confirmación', empty_label=None)
    fecha = forms.DateField(label='Fecha', widget=FECHA)
    hora = forms.TimeField(label='Hora', widget=HORA)
    nota = forms.CharField(label='Nota', max_length=500, required=False)

    def __init__(self, *args, reunion, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        from Alumnos.models import Tutor
        self.fields['tutor'].queryset = Tutor.objects.filter(reuniones_con_familia__reunion=reunion)
        self.fields['tutor'].label_from_instance = nombre_de_persona
        self.fields['tutor'].initial = reunion.tutor_id
        self.fields['recibio'].queryset = (cuentas_del_modulo() | get_user_model().objects.filter(pk=usuario.pk)).distinct().order_by('first_name')
        self.fields['recibio'].initial = usuario.pk
        ahora = timezone.localtime()
        self.fields['fecha'].initial, self.fields['hora'].initial = ahora.date(), ahora.time().replace(second=0, microsecond=0)
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        if datos.get('fecha') and datos.get('hora'):
            from .notificaciones import momento
            datos['momento'] = momento(datos['fecha'], datos['hora'])
            if datos['momento'] > timezone.now() + timedelta(minutes=5):
                self.add_error('hora', 'No puede ser en el futuro.')
        return datos


class AvisoForm(ConfirmarTutorForm):
    """Un aviso hecho a la familia (por teléfono u otro medio): solo se anota."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tutor'].label = 'A quién se avisó'
        self.fields['recibio'].label = 'Quién avisó'
        self.fields['nota'].label = 'Qué se le dijo'
        self.aplicar_estilo()


class DisponibilidadForm(EstiloCamposMixin, forms.Form):
    disponible = forms.TypedChoiceField(label='¿Está disponible en ese horario?', coerce=lambda v: v == 'si',
                                        choices=[('si', 'Sí, estoy disponible'), ('no', 'No estoy disponible')],
                                        widget=forms.RadioSelect(attrs=CASILLA), initial='si')
    nota = forms.CharField(label='Nota', max_length=300, required=False, help_text='Obligatoria si no está disponible.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()


class _ConCasillasDePersonas(EstiloCamposMixin, forms.Form):
    """Una casilla por participante (p_<id>) y por tutor (t_<id>)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def _casillas(self, reunion, etiqueta_personal, etiqueta_tutor, marcadas=True):
        from .disponibilidad import nombre_de_usuario
        self.personal = list(reunion.participantes.filter(activo=True).select_related('usuario'))
        self.invitados = list(reunion.tutores.select_related('tutor'))
        for p in self.personal:
            self.fields[f'p_{p.pk}'] = forms.BooleanField(required=False, initial=marcadas, widget=forms.CheckboxInput(attrs=CASILLA),
                                                          label=f'{nombre_de_usuario(p.usuario)} · {p.get_papel_display()}')
        for t in self.invitados:
            self.fields[f't_{t.pk}'] = forms.BooleanField(required=False, initial=marcadas, widget=forms.CheckboxInput(attrs=CASILLA),
                                                          label=f'{nombre_de_persona(t.tutor)} · {"Solicitó la reunión" if t.solicitante else "Tutor"}')
        self.etiqueta_personal, self.etiqueta_tutor = etiqueta_personal, etiqueta_tutor

    def casillas_de_personal(self):
        return [self[f'p_{p.pk}'] for p in self.personal]

    def casillas_de_tutores(self):
        return [self[f't_{t.pk}'] for t in self.invitados]

    def marcados(self):
        datos = self.cleaned_data
        return ({p.pk for p in self.personal if datos.get(f'p_{p.pk}')}, {t.pk for t in self.invitados if datos.get(f't_{t.pk}')})


class IniciarForm(_ConCasillasDePersonas):
    def __init__(self, *args, reunion, **kwargs):
        super().__init__(*args, **kwargs)
        self._casillas(reunion, 'Personal del colegio presente', 'Familia presente')
        self.aplicar_estilo()


class InasistenciaForm(_ConCasillasDePersonas):
    nota = forms.CharField(label='Observaciones', max_length=1000, required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, reunion, **kwargs):
        super().__init__(*args, **kwargs)
        self._casillas(reunion, 'Del colegio, quién faltó', 'De la familia, quién faltó', marcadas=False)
        self.aplicar_estilo()


class SustitutoForm(EstiloCamposMixin, forms.Form):
    nuevo = CampoDeCuenta(queryset=None, label='Acompañante sustituto', empty_label='Elige al sustituto',
                          help_text='Solo aparecen quienes están autorizados para estos niveles y libres en ese horario.')
    ausente = forms.ModelChoiceField(queryset=None, required=False, label='Sustituye a', empty_label='A nadie (se agrega otro acompañante)')
    motivo = forms.CharField(label='Motivo', max_length=300)

    def __init__(self, *args, reunion, **kwargs):
        super().__init__(*args, **kwargs)
        from .alcance import inscripciones_de
        from .disponibilidad import disponibilidad_de, nombre_de_usuario
        ocupados = set(reunion.participantes.filter(activo=True, papel__in=('DOCENTE', 'ACOMPANANTE')).values_list('usuario_id', flat=True))
        libres = [u.pk for u in candidatos_a_acompanar(inscripciones_de(reunion), excluir=ocupados) if not disponibilidad_de(u, reunion)]
        self.fields['nuevo'].queryset = get_user_model().objects.filter(pk__in=libres).order_by('first_name', 'last_name')
        acompanantes = reunion.participantes.filter(activo=True, papel='ACOMPANANTE').select_related('usuario')
        self.fields['ausente'].queryset = acompanantes
        self.fields['ausente'].label_from_instance = lambda p: nombre_de_usuario(p.usuario)
        if acompanantes.count() == 1:
            self.fields['ausente'].initial = acompanantes.first().pk
        self.aplicar_estilo()


class MinutaForm(EstiloCamposMixin, forms.Form):
    inicio_real = forms.TimeField(label='Hora real de inicio', widget=HORA)
    fin_real = forms.TimeField(label='Hora real de término', widget=HORA)
    temas = forms.CharField(label='Temas tratados', max_length=3000, widget=forms.Textarea(attrs={'rows': 3}))
    resumen = forms.CharField(label='Resumen de la reunión', max_length=5000, widget=forms.Textarea(attrs={'rows': 4}),
                              help_text='Aparece en la minuta para la familia.')
    notas_internas = forms.CharField(label='Notas internas confidenciales', max_length=5000, required=False,
                                     widget=forms.Textarea(attrs={'rows': 3}),
                                     help_text='Nunca aparecen en el portal del tutor ni en la minuta para la familia.')
    siguiente_reunion = forms.BooleanField(required=False, label='Se necesita otra reunión', widget=forms.CheckboxInput(attrs=CASILLA))
    siguiente_reunion_nota = forms.CharField(label='Para qué', max_length=300, required=False)

    def __init__(self, *args, reunion, confidencial, **kwargs):
        super().__init__(*args, **kwargs)
        self.acompanantes = []
        if reunion.estado == Reunion.EN_CURSO:
            from .disponibilidad import nombre_de_usuario
            ahora = timezone.localtime()
            self.fields['inicio_real'].initial = timezone.localtime(reunion.iniciada_en).time().replace(second=0, microsecond=0) if reunion.iniciada_en else reunion.hora_inicio
            self.fields['fin_real'].initial = ahora.time().replace(second=0, microsecond=0)
            self.acompanantes = list(reunion.participantes.filter(asistencia='PRESENTE', papel='ACOMPANANTE').select_related('usuario'))
            for p in self.acompanantes:
                self.fields[f'toda_{p.pk}'] = forms.BooleanField(required=False, initial=True, widget=forms.CheckboxInput(attrs=CASILLA),
                                                                 label=f'{nombre_de_usuario(p.usuario)} estuvo durante toda la reunión')
        if not confidencial:
            del self.fields['notas_internas']
        self.aplicar_estilo()

    def casillas_de_acompanantes(self):
        return [self[f'toda_{p.pk}'] for p in self.acompanantes]

    def presentes_toda(self):
        return {p.pk for p in self.acompanantes if self.cleaned_data.get(f'toda_{p.pk}')}


class CancelarForm(EstiloCamposMixin, forms.Form):
    motivo = forms.CharField(label='Motivo de la cancelación', max_length=1000, widget=forms.Textarea(attrs={'rows': 3}),
                             help_text='Queda en el historial. A la familia y al personal solo se les avisa que se canceló.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()


class AcuerdoForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = Acuerdo
        fields = ['descripcion', 'quien', 'responsable', 'responsable_texto', 'fecha_limite', 'compartido']
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 2}), 'fecha_limite': FECHA,
                   'compartido': forms.CheckboxInput(attrs=CASILLA)}

    def __init__(self, *args, reunion, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsable'] = CampoDeCuenta(queryset=cuentas_del_modulo(), required=False, label='Responsable del seguimiento',
                                                   empty_label='Sin asignar', initial=self.instance.responsable_id or reunion.responsable_id)
        self.fields['responsable_texto'].help_text = 'P. ej. «La mamá de Lucía». Opcional.'
        self.aplicar_estilo()


class SeguimientoAcuerdoForm(EstiloCamposMixin, forms.Form):
    estado = forms.ChoiceField(label='Estado', choices=Acuerdo.ESTADOS)
    nota = forms.CharField(label='Observaciones del seguimiento', max_length=1000, widget=forms.Textarea(attrs={'rows': 2}))
    evidencia = forms.FileField(label='Evidencia', required=False, help_text=AYUDA_DE_ARCHIVOS,
                                widget=forms.ClearableFileInput(attrs={'accept': ACEPTA}))

    def __init__(self, *args, acuerdo, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['estado'].initial = acuerdo.estado
        self.aplicar_estilo()

    def clean_evidencia(self):
        archivo = self.cleaned_data.get('evidencia')
        if archivo:
            from Conducta.forms import validar_archivo
            self.tipo_evidencia = validar_archivo(archivo)
        return archivo


class DocumentosForm(EstiloCamposMixin, forms.Form):
    """Los archivos llegan en request.FILES.getlist('archivos'); el campo solo cuelga sus errores."""

    archivos = forms.FileField(label='Archivos', required=False, help_text=AYUDA_DE_ARCHIVOS,
                               widget=forms.ClearableFileInput(attrs={'accept': ACEPTA}))
    clase = forms.ChoiceField(label='Tipo', choices=AdjuntoReunion.CLASES)
    compartido = forms.BooleanField(required=False, label='Compartir con la familia (aparece en su portal)',
                                    widget=forms.CheckboxInput(attrs=CASILLA))

    def __init__(self, *args, archivos=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lista = list(archivos or [])
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        from django.core.exceptions import ValidationError

        from Conducta.forms import validar_archivo
        if not self.lista:
            self.add_error('archivos', 'Elige al menos un archivo.')
        if len(self.lista) > 10:
            self.add_error('archivos', 'Sube hasta 10 archivos a la vez.')
        validos = []
        for archivo in self.lista[:10]:
            try:
                validos.append((archivo, validar_archivo(archivo)))
            except ValidationError as error:
                self.add_error('archivos', error)
        datos['validos'] = validos
        return datos


# ---------------------------------------------------------------------------
# Filtros de la agenda y la lista
# ---------------------------------------------------------------------------
class FiltroForm(EstiloCamposMixin, forms.Form):
    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Folio, tutor o estudiante…', 'autocomplete': 'off'}))
    nivel = forms.ChoiceField(choices=[('', 'Todos los niveles')], required=False, label='Nivel')
    grupo = forms.ModelChoiceField(Grupo.objects.none(), required=False, empty_label='Todos los grupos', label='Grupo')
    estudiante = forms.CharField(required=False, label='Estudiante', max_length=80)
    tutor = forms.CharField(required=False, label='Tutor', max_length=80)
    participante = CampoDeCuenta(queryset=None, required=False, empty_label='Cualquiera', label='Participante')
    estado = forms.ChoiceField(choices=[('', 'Todos los estados'), ('ABIERTAS', 'Abiertas (sin terminar)'), *Reunion.ESTADOS],
                               required=False, label='Estado')
    prioridad = forms.ChoiceField(choices=[('', 'Todas'), *Reunion.PRIORIDADES], required=False, label='Prioridad')
    desde = forms.DateField(required=False, label='Desde', widget=FECHA)
    hasta = forms.DateField(required=False, label='Hasta', widget=FECHA)

    def __init__(self, *args, acceso, **kwargs):
        super().__init__(*args, **kwargs)
        alcance = acceso.alcance if not acceso.ve_todo else None
        from Prefectura.alcance import TOTAL
        alcance = alcance or TOTAL
        self.fields['grupo'].queryset = alcance.grupos_visibles()
        self.fields['nivel'].choices = [('', 'Todos los niveles' if alcance.total else 'Todos mis niveles'), *alcance.niveles_visibles()]
        self.fields['participante'].queryset = get_user_model().objects.filter(
            participaciones_en_reuniones__reunion__in=acceso.reuniones()).distinct().order_by('first_name', 'last_name')
        self.aplicar_estilo()

    def datos(self):
        self.is_valid()
        return {k: v for k, v in (getattr(self, 'cleaned_data', None) or {}).items() if k not in self.errors}

    @staticmethod
    def _por_nombre(prefijo, palabra):
        return (Q(**{f'{prefijo}__nombre__icontains': palabra}) | Q(**{f'{prefijo}__apellido_paterno__icontains': palabra})
                | Q(**{f'{prefijo}__apellido_materno__icontains': palabra}))

    def filtrar(self, consulta, con_fechas=True):
        datos = self.datos()
        if con_fechas and datos.get('desde'):
            consulta = consulta.filter(fecha__gte=datos['desde'])
        if con_fechas and datos.get('hasta'):
            consulta = consulta.filter(fecha__lte=datos['hasta'])
        if datos.get('nivel'):
            consulta = consulta.filter(estudiantes__inscripcion__grado__nivel=datos['nivel'])
        if datos.get('grupo'):
            consulta = consulta.filter(estudiantes__inscripcion__grupo=datos['grupo'])
        for palabra in (datos.get('estudiante') or '').split():
            consulta = consulta.filter(self._por_nombre('estudiantes__alumno', palabra))
        for palabra in (datos.get('tutor') or '').split():
            consulta = consulta.filter(self._por_nombre('tutores__tutor', palabra))
        if datos.get('participante'):
            consulta = consulta.filter(participantes__usuario=datos['participante'], participantes__activo=True)
        if datos.get('estado') == 'ABIERTAS':
            consulta = consulta.filter(estado__in=Reunion.ABIERTAS)
        elif datos.get('estado'):
            consulta = consulta.filter(estado=datos['estado'])
        if datos.get('prioridad'):
            consulta = consulta.filter(prioridad=datos['prioridad'])
        for palabra in (datos.get('q') or '').split():
            consulta = consulta.filter(Q(folio__icontains=palabra) | self._por_nombre('tutores__tutor', palabra)
                                       | self._por_nombre('estudiantes__alumno', palabra))
        return consulta.distinct()

    @property
    def activos(self):
        return sum(1 for clave, valor in self.datos().items() if valor and clave != 'q')


# ---------------------------------------------------------------------------
# Ajustes › Reuniones
# ---------------------------------------------------------------------------
class ConfiguracionForm(EstiloCamposMixin, forms.ModelForm):
    dias = forms.TypedMultipleChoiceField(label='Días de atención', choices=DIAS, coerce=int,
                                          widget=forms.CheckboxSelectMultiple(attrs=CASILLA))

    class Meta:
        model = ConfiguracionReuniones
        fields = ['dias', 'hora_apertura', 'hora_cierre', 'duracion', 'recordatorio_horas', 'aviso_acuerdos_dias']
        widgets = {'hora_apertura': HORA, 'hora_cierre': HORA}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['hora_apertura'].label = 'Horario de atención: desde'
        self.fields['hora_cierre'].label = 'Hasta'
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        if datos.get('hora_apertura') and datos.get('hora_cierre') and datos['hora_cierre'] <= datos['hora_apertura']:
            self.add_error('hora_cierre', 'Debe ser después de la hora de inicio.')
        if 'dias' in datos and not datos['dias']:
            self.add_error('dias', 'Elige al menos un día.')
        return datos


class MotivoForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = MotivoReunion
        fields = ['nombre', 'orden', 'activo']
        widgets = {'activo': forms.CheckboxInput(attrs=CASILLA)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()


class SalaForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = SalaReunion
        fields = ['nombre', 'ubicacion', 'orden', 'activo']
        widgets = {'activo': forms.CheckboxInput(attrs=CASILLA)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()
