"""Formularios de los bloques simultáneos y sus opciones. Lo que depende de todo el sistema (empalmes, población, plan de
estudios) se valida en Asignaciones/bloques.py; aquí, la forma de los datos."""
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from Alumnos.forms import EstiloCamposMixin
from Alumnos.horarios import DIAS, DIAS_HABILES
from Alumnos.models import (
    BloqueSimultaneo, CicloEscolar, Grado, Grupo, GrupoClase, HorarioMateria, Materia, MateriaGrado, Profesor, Semestre, orden_de_nivel,
)
from Alumnos.semanas import Calendario
from Alumnos.utils import compactar_espacios

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
HORA = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')


class GrupoOrigenField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, grupo):
        return str(grupo)


class BloqueForm(EstiloCamposMixin, forms.ModelForm):
    """Nombre, nivel, ciclo, semestre, vigencia y grupos de origen. Un bloque activo solo cambia de nombre y de fin de
    vigencia; lo demás se cambia desactivándolo."""

    grupos_origen = GrupoOrigenField(Grupo.objects.none(), widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}), label='Grupos de origen',
                                     error_messages={'required': 'Elige al menos un grupo de origen.'})

    class Meta:
        model = BloqueSimultaneo
        fields = ['nombre', 'nivel', 'ciclo', 'semestre', 'vigente_desde', 'vigente_hasta', 'mezclar_grados', 'poblacion_delimitada', 'grupos_origen']
        widgets = {
            'nombre': forms.TextInput(attrs={'placeholder': 'Talleres de bachillerato', 'autocomplete': 'off'}),
            'vigente_desde': FECHA, 'vigente_hasta': FECHA,
            'mezclar_grados': forms.CheckboxInput(attrs={'class': 'choice__input'}),
            'poblacion_delimitada': forms.CheckboxInput(attrs={'class': 'choice__input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.activo = self.instance.pk is not None and self.instance.activo
        self.fields['ciclo'].queryset = CicloEscolar.objects.vigentes() if self.instance.pk is None else CicloEscolar.objects.filter(pk=self.instance.ciclo_id)
        self.fields['ciclo'].empty_label = None
        self.fields['nivel'].choices = [c for c in self.fields['nivel'].choices if c[0]]
        self.fields['semestre'].queryset = Semestre.objects.filter(ciclo__in=self.fields['ciclo'].queryset).select_related('ciclo')
        self.fields['semestre'].empty_label = 'No aplica'
        self.fields['semestre'].required = False
        propios = list(self.instance.grupos_origen.values_list('pk', flat=True)) if self.instance.pk else []
        self.fields['grupos_origen'].queryset = (
            Grupo.objects.filter(Q(pk__in=Grupo.objects.disponibles()) | Q(pk__in=propios)).select_related('grado', 'nombre').academicos()
        )
        if self.activo:
            for nombre in ('nivel', 'ciclo', 'semestre', 'vigente_desde', 'mezclar_grados', 'poblacion_delimitada', 'grupos_origen'):
                self.fields[nombre].disabled = True
        self.aplicar_estilo()

    def clean_nombre(self):
        return compactar_espacios(self.cleaned_data.get('nombre'))

    def clean(self):
        datos = super().clean()
        ciclo, nivel, semestre = datos.get('ciclo'), datos.get('nivel'), datos.get('semestre')
        desde, hasta, grupos = datos.get('vigente_desde'), datos.get('vigente_hasta'), datos.get('grupos_origen')
        if desde and hasta and hasta < desde:
            self.add_error('vigente_hasta', 'La vigencia debe terminar después de empezar.')
        if ciclo and desde and hasta and (desde < ciclo.fecha_inicio or hasta > ciclo.fecha_fin):
            self.add_error('vigente_desde', f'La vigencia debe quedar dentro del ciclo ({ciclo.fecha_inicio:%d/%m/%Y} al {ciclo.fecha_fin:%d/%m/%Y}).')
        if semestre is not None and ciclo is not None and semestre.ciclo_id != ciclo.pk:
            self.add_error('semestre', 'Ese semestre es de otro ciclo.')
        if nivel == 'PREPARATORIA' and ciclo is not None and semestre is None and Semestre.objects.filter(ciclo=ciclo).exists():
            self.add_error('semestre', 'Elige el semestre: en bachillerato cada bloque es de un semestre.')
        if semestre is not None and nivel != 'PREPARATORIA':
            self.add_error('semestre', 'Solo bachillerato maneja semestres.')
        if semestre is not None and desde and hasta and (desde < semestre.fecha_inicio or hasta > semestre.fecha_fin):
            self.add_error('vigente_desde', f'La vigencia debe quedar dentro del {semestre.en_frase} ({semestre.fecha_inicio:%d/%m/%Y} al {semestre.fecha_fin:%d/%m/%Y}).')
        if grupos and nivel:
            ajenos = [g for g in grupos if g.grado.nivel != nivel]
            if ajenos:
                self.add_error('grupos_origen', f'{ajenos[0]} no es de {dict(Grado.NIVEL_CHOICES)[nivel]}: un bloque no mezcla niveles educativos.')
            if len({g.grado_id for g in grupos}) > 1 and not datos.get('mezclar_grados'):
                self.add_error('grupos_origen', 'Son de distintos grados: activa «Permitir mezclar grados del mismo nivel» para combinarlos.')
            if semestre is not None:
                ajenos = [g for g in grupos if g.grado.semestre != semestre.clave]
                if ajenos:
                    self.add_error('grupos_origen', f'{ajenos[0]} no se cursa en el {semestre.en_frase}.')
        return datos


class HorariosForm(forms.Form):
    """Los días y horarios del bloque: una hora por día y, si el nivel alterna, la semana."""

    semana = forms.ChoiceField(required=False, choices=HorarioMateria.SEMANA_CHOICES, label='Semana')

    def __init__(self, *args, bloque, **kwargs):
        super().__init__(*args, **kwargs)
        self.bloque = bloque
        self.alternado = Calendario(bloque.ciclo).alternado(bloque.nivel)
        actuales = {h.dia_semana: h for h in bloque.horarios.all()}
        for dia in DIAS_HABILES:
            actual = actuales.get(dia)
            self.fields[f'dia_{dia}'] = forms.BooleanField(required=False, label=DIAS[dia], initial=actual is not None,
                                                           widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))
            self.fields[f'inicio_{dia}'] = forms.TimeField(required=False, label='Inicio', widget=HORA, initial=actual.hora_inicio if actual else None)
            self.fields[f'fin_{dia}'] = forms.TimeField(required=False, label='Fin', widget=HORA, initial=actual.hora_fin if actual else None)
            for nombre in (f'inicio_{dia}', f'fin_{dia}'):
                self.fields[nombre].widget.attrs['class'] = 'field__control'
        if actuales:
            self.fields['semana'].initial = next(iter(actuales.values())).semana
        self.fields['semana'].widget.attrs['class'] = 'field__control field__control--select'

    @property
    def dias(self):
        return [{'nombre': DIAS[d], 'marcado': self[f'dia_{d}'], 'inicio': self[f'inicio_{d}'], 'fin': self[f'fin_{d}']} for d in DIAS_HABILES]

    def clean(self):
        datos = super().clean()
        semana = datos.get('semana') or ''
        if semana and not self.alternado:
            self.add_error('semana', f'{self.bloque.get_nivel_display()} tiene horario fijo: el bloque es de todas las semanas.')
        filas = []
        for dia in DIAS_HABILES:
            if not datos.get(f'dia_{dia}'):
                continue
            inicio, fin = datos.get(f'inicio_{dia}'), datos.get(f'fin_{dia}')
            if not inicio or not fin:
                self.add_error(f'inicio_{dia}', f'Indica la hora de inicio y de fin del {DIAS[dia].lower()}.')
            elif inicio >= fin:
                self.add_error(f'inicio_{dia}', 'La hora de inicio debe ser anterior a la de fin.')
            else:
                filas.append((dia, inicio, fin, semana))
        if not filas and not self.errors:
            raise ValidationError('Elige al menos un día.')
        datos['filas'] = filas
        return datos


class AsignacionBaseField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, asignacion):
        return f'{asignacion.materia} · {asignacion.grupo}'


class SustituyeForm(forms.Form):
    """Las clases del horario de los grupos de origen que el bloque sustituye para sus estudiantes."""

    sustituye = AsignacionBaseField(MateriaGrado.objects.none(), required=False, widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
                                    label='Clases que sustituye')

    def __init__(self, *args, bloque, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sustituye'].queryset = (
            MateriaGrado.objects.de_plan().filter(ciclo=bloque.ciclo, activa=True, grupo__in=bloque.grupos_origen.all())
            .select_related('materia', 'grupo__nombre', 'grupo__grado').order_by('materia__nombre', 'grupo__nombre__orden')
        )
        self.fields['sustituye'].initial = list(bloque.sustituye.values_list('pk', flat=True))


class OpcionForm(EstiloCamposMixin, forms.Form):
    """Una opción del bloque: nombre, materia del catálogo, docente, aula y, si el bloque mezcla grados, la materia del plan
    que cursan en ella los estudiantes de cada grado."""

    nombre = forms.CharField(max_length=80, label='Nombre', widget=forms.TextInput(attrs={'placeholder': 'Inglés básico', 'autocomplete': 'off'}),
                             error_messages={'required': 'Escribe el nombre de la opción.'})
    materia = forms.ModelChoiceField(Materia.objects.none(), label='Materia', empty_label='Elige la materia…', error_messages={'required': 'Elige la materia.'})
    profesor = forms.ModelChoiceField(Profesor.objects.none(), required=False, label='Docente responsable', empty_label='Sin docente todavía')
    aula = forms.CharField(max_length=60, required=False, label='Aula', widget=forms.TextInput(attrs={'autocomplete': 'off', 'list': 'aulas-usadas'}))

    def __init__(self, *args, bloque, clase=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bloque, self.clase = bloque, clase
        grados = {g.grado_id: g.grado for g in bloque.grupos_origen.select_related('grado')}
        self.fields['materia'].queryset = Materia.objects.filter(Q(grado__in=list(grados)) | Q(grado__isnull=True), activa=True).order_by('nombre')
        self.fields['profesor'].queryset = Profesor.objects.filter(estatus='ACTIVO', niveles__nivel=bloque.nivel).distinct().order_by('apellido_paterno', 'nombre')
        self.grados_extra = []
        if bloque.mezclar_grados and len(grados) > 1:
            actuales = {e.grado_id: e.materia_id for e in clase.equivalencias.all()} if clase else {}
            for grado in sorted(grados.values(), key=lambda g: g.numero):
                nombre = f'equivalencia_{grado.pk}'
                self.fields[nombre] = forms.ModelChoiceField(
                    Materia.objects.filter(Q(grado=grado) | Q(grado__isnull=True), activa=True).order_by('nombre'), required=False,
                    label=f'Materia del plan para {grado}', empty_label='La misma de la opción', initial=actuales.get(grado.pk),
                )
                self.grados_extra.append((grado, nombre))
        if clase is not None:
            self.fields['nombre'].initial = clase.nombre
            self.fields['materia'].initial = clase.asignacion.materia_id
            self.fields['profesor'].initial = clase.asignacion.profesor_id
            self.fields['aula'].initial = clase.aula
        self.aulas = sorted(set(GrupoClase.objects.filter(bloque__ciclo=bloque.ciclo).exclude(aula='').values_list('aula', flat=True)))
        self.aplicar_estilo()

    def clean_nombre(self):
        return compactar_espacios(self.cleaned_data.get('nombre'))

    def clean_aula(self):
        return compactar_espacios(self.cleaned_data.get('aula') or '')

    def clean(self):
        datos = super().clean()
        datos['equivalencias'] = {grado: datos[nombre] for grado, nombre in self.grados_extra if datos.get(nombre)}
        return datos

    def datos(self):
        return {clave: self.cleaned_data.get(clave) for clave in ('nombre', 'materia', 'profesor', 'aula', 'equivalencias')}


class FechaEfectivaForm(forms.Form):
    fecha = forms.DateField(required=False, label='Fecha efectiva', widget=forms.DateInput(attrs={'type': 'date', 'class': 'field__control'}, format='%Y-%m-%d'))

    def fecha_o_hoy(self):
        self.is_valid()
        return self.cleaned_data.get('fecha') or timezone.localdate()


class FiltroEstudiantesForm(EstiloCamposMixin, forms.Form):
    """Filtros de la distribución: grado, grupo base, opción (o pendientes) y búsqueda."""

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={'type': 'search', 'placeholder': 'Nombre o referencia…', 'autocomplete': 'off'}))
    grado = forms.ChoiceField(required=False, label='Grado')
    grupo = forms.ChoiceField(required=False, label='Grupo base')
    opcion = forms.ChoiceField(required=False, label='Opción')

    def __init__(self, *args, bloque, **kwargs):
        super().__init__(*args, **kwargs)
        grupos = list(bloque.grupos_origen.select_related('grado', 'nombre').order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre__orden'))
        grados = {g.grado_id: g.grado for g in grupos}
        self.fields['grado'].choices = [('', 'Todos los grados')] + [(pk, str(g)) for pk, g in grados.items()]
        self.fields['grupo'].choices = [('', 'Todos los grupos')] + [(g.pk, str(g)) for g in grupos]
        self.fields['opcion'].choices = [('', 'Todas las opciones'), ('pendientes', 'Pendientes de asignar')] + [(c.pk, c.nombre) for c in bloque.opciones.all()]
        self.aplicar_estilo()

    def aplicar(self, filas):
        """Las filas de la distribución que cumplen los filtros."""
        self.is_valid()
        datos = getattr(self, 'cleaned_data', {})
        for palabra in (datos.get('q') or '').lower().split():
            filas = [f for f in filas if palabra in str(f['inscripcion'].alumno).lower() or palabra in (f['inscripcion'].alumno.referencia or '').lower()]
        if datos.get('grado'):
            filas = [f for f in filas if str(f['inscripcion'].grado_id) == datos['grado']]
        if datos.get('grupo'):
            filas = [f for f in filas if str(f['inscripcion'].grupo_id) == datos['grupo']]
        if datos.get('opcion') == 'pendientes':
            filas = [f for f in filas if f['integrante'] is None]
        elif datos.get('opcion'):
            filas = [f for f in filas if f['integrante'] is not None and str(f['integrante'].clase_id) == datos['opcion']]
        return filas
