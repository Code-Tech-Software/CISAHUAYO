"""Formularios de la bitácora: la entrada de una clase y los filtros del historial."""
import json
import uuid

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from Alumnos.academico import ciclo_actual
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Alumno, CicloEscolar, Grupo, HorarioMateria, MateriaGrado, Materia, Periodo, orden_de_nivel

from . import reglas

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
DIAS = dict(HorarioMateria.DIA_CHOICES)


def texto_de_bloque(bloque):
    semana = f' · Semana {bloque.semana}' if bloque.semana else ''
    return f'{DIAS[bloque.dia_semana]} {bloque.hora_inicio:%H:%M}–{bloque.hora_fin:%H:%M}{semana}'


class _Asignacion(forms.ModelChoiceField):
    def label_from_instance(self, asignacion):
        return asignacion.materia.nombre


class _Grupo(forms.ModelChoiceField):
    def label_from_instance(self, grupo):
        return str(grupo)


class _Bloque(forms.ModelChoiceField):
    def label_from_instance(self, bloque):
        return texto_de_bloque(bloque)


class EntradaForm(EstiloCamposMixin, forms.Form):
    """La entrada de una clase. `alcance` limita los grupos y materias (Bitacoras/alcance.py); al editar (`entrada`)
    el grupo no cambia y se conservan los estudiantes que ya estaban aunque hayan cambiado de grupo."""

    grupo = _Grupo(Grupo.objects.none(), label='Grupo', empty_label='Elige el grupo…')
    asignacion = _Asignacion(MateriaGrado.objects.none(), label='Materia', empty_label='Elige la materia…')
    fecha = forms.DateField(label='Fecha de la clase', widget=FECHA)
    bloque = _Bloque(HorarioMateria.objects.none(), required=False, label='Bloque u hora', empty_label='Sin bloque')
    general = forms.BooleanField(required=False, label='Observación general del grupo',
                                 help_text='Aparece en la bitácora del grupo, sin atribuirse a ningún estudiante ni a sus reportes individuales.')
    alumnos = forms.ModelMultipleChoiceField(Alumno.objects.none(), required=False, label='Estudiantes implicados',
                                             widget=forms.CheckboxSelectMultiple)
    titulo = forms.CharField(label='Título', max_length=120, widget=forms.TextInput(attrs={'placeholder': 'En pocas palabras: qué pasó'}))
    descripcion = forms.CharField(label='Descripción de lo ocurrido', widget=forms.Textarea(attrs={'rows': 5}))
    seguimiento = forms.CharField(label='Acuerdos o acciones de seguimiento', required=False, widget=forms.Textarea(attrs={'rows': 3}),
                                  help_text='Opcional.')
    clave_envio = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, alcance, entrada=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.alcance, self.entrada = alcance, entrada
        ciclo = entrada.ciclo if entrada else ciclo_actual()
        self.ciclo = ciclo
        asignaciones = alcance.asignaciones(ciclo)
        if entrada is not None:
            # Al editar, el grupo queda fijo; la materia, entre las de ese grupo que puede registrar (y la que ya tenía)
            asignaciones = MateriaGrado.objects.filter(Q(pk__in=asignaciones.filter(grupo=entrada.grupo).values('pk')) | Q(pk=entrada.asignacion_id))
            asignaciones = asignaciones.select_related('materia', 'profesor', 'ciclo', 'grado', 'grupo__nombre', 'grupo__grado').order_by('materia__nombre')
            self.fields['grupo'].required = False
            self.fields['grupo'].disabled = True
        self.asignaciones = list(asignaciones)
        self.fields['asignacion'].queryset = MateriaGrado.objects.filter(pk__in=[a.pk for a in self.asignaciones]).select_related('materia', 'grupo__nombre', 'grupo__grado', 'ciclo')
        grupos = {a.grupo_id for a in self.asignaciones} | ({entrada.grupo_id} if entrada else set())
        self.fields['grupo'].queryset = (Grupo.objects.filter(pk__in=grupos).select_related('grado', 'nombre')
                                         .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre__orden', 'nombre__nombre'))
        # Todas las versiones (una clase pasada pudo darse con un horario anterior); la pantalla ofrece las que
        # corresponden a la fecha (día, semana A/B y vigencia) y aquí se vuelve a revisar
        self.fields['bloque'].queryset = (HorarioMateria.historial.filter(materia_grado__in=self.asignaciones)
                                          .select_related('materia_grado__grado').order_by('dia_semana', 'hora_inicio', 'semana'))
        from Alumnos.semanas import Calendario, mapa_de_semanas
        self.calendario = Calendario(ciclo)
        niveles = {a.grado.nivel for a in self.asignaciones}
        self.semanas_json = json.dumps({nivel: mapa_de_semanas(self.calendario, nivel) for nivel in niveles if self.calendario.alternado(nivel)})
        self.fields['alumnos'].queryset = Alumno.objects.all()
        if entrada is not None:
            self.initial.update({
                'grupo': entrada.grupo_id, 'asignacion': entrada.asignacion_id, 'fecha': entrada.fecha, 'bloque': entrada.bloque_id,
                'general': entrada.general, 'alumnos': list(entrada.alumnos.values_list('pk', flat=True)),
                'titulo': entrada.titulo, 'descripcion': entrada.descripcion, 'seguimiento': entrada.seguimiento,
            })
        else:
            self.initial.setdefault('fecha', timezone.localdate())
            self.initial.setdefault('clave_envio', uuid.uuid4())
        self.aplicar_estilo()

    # ------------------------------------------------------------------ lo elegido (para mostrar los estudiantes)
    def _valor(self, nombre):
        if self.is_bound and not self.fields[nombre].disabled:
            return self.data.get(self.add_prefix(nombre)) or ''
        valor = self.initial.get(nombre)
        return '' if valor is None else str(getattr(valor, 'pk', valor))

    @property
    def grupo_elegido(self):
        valor = self._valor('grupo')
        return next((a.grupo for a in self.asignaciones if str(a.grupo_id) == valor), self.entrada.grupo if self.entrada else None)

    def estudiantes(self):
        """[(alumno, elegido)] del grupo elegido, para las casillas (vacío hasta que se elige el grupo)."""
        grupo = self.grupo_elegido
        if grupo is None:
            return []
        if self.is_bound:
            elegidos = set(self.data.getlist(self.add_prefix('alumnos')))
        else:
            elegidos = {str(pk) for pk in self.initial.get('alumnos') or []}
        return [(alumno, str(alumno.pk) in elegidos) for alumno in reglas.alumnos_elegibles(grupo, self.ciclo, self.entrada)]

    # ------------------------------------------------------------------ validación
    def clean_titulo(self):
        return ' '.join(self.cleaned_data['titulo'].split())

    def clean_descripcion(self):
        return self.cleaned_data['descripcion'].strip()

    def clean_seguimiento(self):
        return (self.cleaned_data.get('seguimiento') or '').strip()

    def clean(self):
        datos = super().clean()
        asignacion, fecha = datos.get('asignacion'), datos.get('fecha')
        grupo = self.entrada.grupo if self.entrada else datos.get('grupo')
        if asignacion is not None and grupo is not None and asignacion.grupo_id != grupo.pk:
            self.add_error('asignacion', 'Esa materia no es de ese grupo: elige una del grupo.')
            asignacion = None
        if fecha is not None:
            ciclo = asignacion.ciclo if asignacion else self.ciclo
            if fecha > timezone.localdate():
                self.add_error('fecha', 'La clase todavía no ocurre: la fecha no puede ser posterior a hoy.')
            elif ciclo is not None and not ciclo.fecha_inicio <= fecha <= ciclo.fecha_fin:
                self.add_error('fecha', f'La fecha queda fuera del ciclo {ciclo} ({ciclo.fecha_inicio:%d/%m/%Y} al {ciclo.fecha_fin:%d/%m/%Y}).')
        bloque = datos.get('bloque')
        if bloque is not None and asignacion is not None:
            if bloque.materia_grado_id != asignacion.pk:
                self.add_error('bloque', 'Ese bloque es de otra materia.')
            elif fecha is not None:
                from Alumnos.semanas import Calendario, explicar
                calendario = self.calendario if self.calendario.ciclo == asignacion.ciclo else Calendario(asignacion.ciclo)
                problema = explicar(bloque, fecha, calendario, asignacion.grado.nivel)
                if problema:
                    self.add_error('bloque', problema)
        if datos.get('general'):
            datos['alumnos'] = []
        else:
            alumnos = list(datos.get('alumnos') or [])
            if not alumnos:
                self.add_error('alumnos', 'Elige al menos a un estudiante o marca «Observación general del grupo».')
            elif grupo is not None and self.ciclo is not None:
                permitidos = set(reglas.alumnos_elegibles(grupo, self.ciclo, self.entrada).values_list('pk', flat=True))
                if any(alumno.pk not in permitidos for alumno in alumnos):
                    self.add_error('alumnos', 'Solo puedes elegir a estudiantes inscritos en ese grupo.')
            datos['alumnos'] = alumnos
        return datos


class AnularForm(forms.Form):
    motivo = forms.CharField(label='Motivo de la anulación', widget=forms.Textarea(attrs={'rows': 3, 'class': 'field__control'}),
                             help_text='Queda en el historial de la entrada. La entrada no se borra: deja de aparecer en la bitácora y en los reportes.')

    def clean_motivo(self):
        motivo = self.cleaned_data['motivo'].strip()
        if len(motivo) < 5:
            raise forms.ValidationError('Explica brevemente el motivo (al menos 5 caracteres).')
        return motivo


# ---------------------------------------------------------------------------
# Filtros del historial
# ---------------------------------------------------------------------------
VIGENTES, ANULADAS, TODAS = '', 'anuladas', 'todas'


class _Autor(forms.ModelChoiceField):
    def label_from_instance(self, usuario):
        return usuario.get_full_name() or usuario.get_username()


class FiltroForm(EstiloCamposMixin, forms.Form):
    """Sin «ciclo» en la dirección se usa el ciclo actual; «Todos los ciclos» es ciclo vacío."""

    grupo = _Grupo(Grupo.objects.none(), required=False, label='Grupo', empty_label='Todos mis grupos')
    ciclo = forms.ModelChoiceField(CicloEscolar.objects.none(), required=False, label='Ciclo escolar', empty_label='Todos los ciclos')
    periodo = forms.ModelChoiceField(Periodo.objects.none(), required=False, label='Periodo', empty_label='Cualquier periodo')
    desde = forms.DateField(required=False, label='Desde', widget=FECHA)
    hasta = forms.DateField(required=False, label='Hasta', widget=FECHA)
    materia = forms.ModelChoiceField(Materia.objects.none(), required=False, label='Materia', empty_label='Todas las materias')
    alumno = forms.ModelChoiceField(Alumno.objects.none(), required=False, label='Estudiante', empty_label='Todos los estudiantes')
    autor = _Autor(get_user_model().objects.none(), required=False, label='Autor', empty_label='Cualquier autor')
    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={'type': 'search', 'placeholder': 'Título, descripción o acuerdos…'}))
    registros = forms.ChoiceField(choices=[(VIGENTES, 'Vigentes'), (ANULADAS, 'Anuladas'), (TODAS, 'Vigentes y anuladas')], required=False, label='Entradas')

    def __init__(self, *args, alcance, **kwargs):
        super().__init__(*args, **kwargs)
        self.alcance = alcance
        visibles = alcance.entradas(anuladas=True)
        self.fields['grupo'].queryset = alcance.grupos()
        self.fields['ciclo'].queryset = CicloEscolar.objects.order_by('-fecha_inicio')
        self.fields['periodo'].queryset = Periodo.objects.filter(pk__in=visibles.values('periodo')).select_related('ciclo').order_by('-ciclo__fecha_inicio', orden_de_nivel('nivel'), 'fecha_inicio')
        self.fields['periodo'].label_from_instance = lambda p: f'{p.nombre} · {p.get_nivel_display()} · {p.ciclo}'
        self.fields['materia'].queryset = Materia.objects.filter(pk__in=visibles.values('materia')).order_by('nombre')
        self.fields['autor'].queryset = get_user_model().objects.filter(pk__in=visibles.values('autor')).order_by('first_name', 'last_name', 'username')
        # Cualquiera se acepta (el filtro solo actúa sobre lo visible); la lista muestra los del grupo elegido
        self.fields['alumno'].queryset = Alumno.objects.all()
        if not alcance.gestiona:
            del self.fields['registros']
        if not self.is_bound or 'ciclo' not in self.data:
            actual = ciclo_actual()
            if self.is_bound:
                self.data = self.data.copy()
                self.data['ciclo'] = str(actual.pk) if actual else ''
            else:
                self.initial.setdefault('ciclo', actual.pk if actual else None)
        self.aplicar_estilo()

    def opciones_de_alumno(self):
        """Los estudiantes que ofrece el filtro: los del grupo elegido (inscritos en él o con entradas en él) y el que ya
        esté elegido. Sin grupo, solo el elegido (el historial completo de un estudiante está en su propia página)."""
        datos = self.datos()
        grupo, elegido = datos.get('grupo'), datos.get('alumno')
        condicion = Q(pk=elegido.pk) if elegido else Q(pk__in=[])
        if grupo is not None:
            condicion |= Q(inscripciones__grupo=grupo) | Q(vinculos_bitacora__entrada__in=self.alcance.entradas(anuladas=True).filter(grupo=grupo))
        return Alumno.objects.filter(condicion).distinct().order_by('apellido_paterno', 'apellido_materno', 'nombre')

    def datos(self):
        if not self.is_bound:
            return {}
        self.is_valid()
        return {k: v for k, v in (getattr(self, 'cleaned_data', None) or {}).items() if k not in self.errors}

    def aplicar(self, entradas=None):
        """(entradas filtradas, aviso). El aviso explica por qué no hay resultados por fechas."""
        datos = self.datos()
        registros = datos.get('registros') or VIGENTES
        entradas = self.alcance.entradas(anuladas={VIGENTES: False, ANULADAS: 'solo', TODAS: True}[registros]) if entradas is None else entradas
        ciclo = datos.get('ciclo')
        if ciclo is None and not (self.is_bound and 'ciclo' in self.data):
            ciclo = ciclo_actual()
        if ciclo is not None:
            entradas = entradas.filter(ciclo=ciclo)
        inicio, fin, periodo = datos.get('desde'), datos.get('hasta'), datos.get('periodo')
        if periodo is not None:
            entradas = entradas.filter(periodo=periodo)
        if inicio and fin and inicio > fin:
            return entradas.none(), 'La fecha inicial va después de la final: no hay fechas en común.'
        if inicio:
            entradas = entradas.filter(fecha__gte=inicio)
        if fin:
            entradas = entradas.filter(fecha__lte=fin)
        for campo in ('grupo', 'materia', 'autor'):
            if datos.get(campo) is not None:
                entradas = entradas.filter(**{campo: datos[campo]})
        if datos.get('alumno') is not None:
            entradas = entradas.filter(vinculos__alumno=datos['alumno'])
        for palabra in (datos.get('q') or '').split():
            entradas = entradas.filter(Q(titulo__icontains=palabra) | Q(descripcion__icontains=palabra) | Q(seguimiento__icontains=palabra)
                                       | Q(materia_nombre__icontains=palabra))
        return entradas.distinct(), None

    @property
    def activos(self):
        """Cuántos filtros de «Más filtros» hay aplicados (para dejarlo abierto)."""
        datos = self.datos()
        return sum(1 for clave in ('periodo', 'desde', 'hasta', 'autor', 'registros') if datos.get(clave))
