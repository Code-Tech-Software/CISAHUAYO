from django import forms
from django.db.models import Exists, OuterRef, Q

from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import CicloEscolar, Grado, HorarioMateria, Materia, Profesor, ProfesorMateria
from Alumnos.utils import compactar_espacios


class ProfesorChoiceField(forms.ModelChoiceField):
    """Selector de profesor; quien está de baja se distingue porque aún puede figurar en ciclos cerrados."""

    def label_from_instance(self, profesor):
        return f'{profesor} (de baja)' if profesor.estatus != 'ACTIVO' else str(profesor)


class FiltroAsignacionesForm(EstiloCamposMixin, forms.Form):
    """Filtros del tablero y de la exportación: texto, grado, profesor y estado de la asignación."""

    ESTADO_CHOICES = [
        ('', 'Cualquier estado'),
        ('sin_profesor', 'Sin profesor'),
        ('con_profesor', 'Con profesor'),
        ('no_habilitado', 'Profesor sin habilitar'),
        ('sin_horario', 'Sin horario'),
    ]

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Materia, clave o profesor…', 'autocomplete': 'off',
    }))
    grado = forms.ModelChoiceField(Grado.objects.none(), required=False, label='Grado', empty_label='Todos los grados')
    profesor = ProfesorChoiceField(Profesor.objects.none(), required=False, label='Profesor', empty_label='Todos los profesores')
    estado = forms.ChoiceField(required=False, choices=ESTADO_CHOICES, label='Estado')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['grado'].queryset = Grado.objects.all().academicos()
        self.fields['profesor'].queryset = Profesor.objects.all()
        self.aplicar_estilo()

    @property
    def activos(self):
        """Valores válidos de los filtros (los inválidos de la URL se ignoran)."""
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}

    def filtrar(self, queryset):
        datos = self.activos

        for palabra in datos.get('q', '').split():
            queryset = queryset.filter(
                Q(materia__nombre__icontains=palabra) | Q(materia__clave__icontains=palabra)
                | Q(profesor__nombre__icontains=palabra) | Q(profesor__apellido_paterno__icontains=palabra)
                | Q(profesor__apellido_materno__icontains=palabra)
            )
        if 'grado' in datos:
            queryset = queryset.filter(grado=datos['grado'])
        if 'profesor' in datos:
            queryset = queryset.filter(profesor=datos['profesor'])

        estado = datos.get('estado')
        if estado == 'sin_profesor':
            queryset = queryset.filter(profesor__isnull=True)
        elif estado == 'con_profesor':
            queryset = queryset.filter(profesor__isnull=False)
        elif estado == 'no_habilitado':
            habilitado = ProfesorMateria.objects.filter(profesor=OuterRef('profesor_id'), materia=OuterRef('materia_id'))
            queryset = queryset.filter(profesor__isnull=False).filter(~Exists(habilitado))
        elif estado == 'sin_horario':
            queryset = queryset.filter(~Exists(HorarioMateria.objects.filter(materia_grado=OuterRef('pk'))))
        return queryset


class AsignacionAcademicaForm(EstiloCamposMixin, forms.Form):
    """Todo en un solo paso: ciclo, materia (del catálogo o nueva), los grados donde se imparte y quién la da.

    El profesor puede ser el mismo para todos los grados elegidos o uno distinto por grado (`profesor_<id del grado>`).
    Crear una materia pide permiso de crear materias, y elegir profesores, el de cambiar la asignación.
    """

    ORIGENES = [('existente', 'Una materia del catálogo'), ('nueva', 'Una materia nueva')]

    ciclo = forms.ModelChoiceField(queryset=CicloEscolar.objects.none(), label='Ciclo escolar', empty_label=None)
    origen = forms.ChoiceField(choices=ORIGENES, initial='existente', label='Materia', widget=forms.RadioSelect)
    materia = forms.ModelChoiceField(queryset=Materia.objects.none(), required=False, label='Materia', empty_label='Elige la materia')
    nueva_nombre = forms.CharField(required=False, max_length=100, label='Nombre de la materia', widget=forms.TextInput(attrs={
        'placeholder': 'Matemáticas', 'autocomplete': 'off',
    }))
    nueva_clave = forms.CharField(required=False, max_length=20, label='Clave', widget=forms.TextInput(attrs={
        'placeholder': 'MAT', 'autocapitalize': 'characters', 'autocomplete': 'off', 'spellcheck': 'false',
    }), help_text='Código corto y único: letras, números, punto o guion.')
    grados = forms.ModelMultipleChoiceField(
        queryset=Grado.objects.none(), label='Grados', widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        error_messages={'required': 'Elige al menos un grado.', 'invalid_choice': 'Elige grados de la lista.'},
    )
    profesor = ProfesorChoiceField(queryset=Profesor.objects.none(), required=False, label='Profesor',
                                   empty_label='Sin profesor por ahora')
    por_grado = forms.BooleanField(required=False, label='Un profesor distinto en cada grado')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        from Alumnos.academico import ciclo_editable

        self.actor = actor
        self.puede_crear_materias = actor.has_perm('Alumnos.add_materia')
        self.puede_asignar_profesores = actor.has_perm('Alumnos.change_materiagrado')
        editables = [ciclo for ciclo in CicloEscolar.objects.all() if ciclo_editable(ciclo)]
        self.fields['ciclo'].queryset = CicloEscolar.objects.filter(pk__in=[ciclo.pk for ciclo in editables])
        self.fields['ciclo'].label_from_instance = lambda ciclo: f'{ciclo.nombre} · {ciclo.estado_display.lower()}'
        if not self.fields['ciclo'].initial and editables:
            self.fields['ciclo'].initial = next((ciclo.pk for ciclo in editables if ciclo.activo), editables[0].pk)
        if not self.puede_crear_materias:
            self.fields['origen'].choices = self.ORIGENES[:1]
        self.fields['materia'].queryset = Materia.objects.filter(activa=True).order_by('nombre')
        self.fields['materia'].label_from_instance = lambda materia: f'{materia.nombre} ({materia.clave})'
        self.grados_disponibles = list(Grado.objects.filter(activo=True).academicos())
        self.fields['grados'].queryset = Grado.objects.filter(activo=True)
        activos = Profesor.objects.filter(estatus='ACTIVO')
        self.fields['profesor'].queryset = activos
        for grado in self.grados_disponibles:
            self.fields[f'profesor_{grado.pk}'] = ProfesorChoiceField(
                queryset=activos, required=False, label=f'Profesor de {grado}', empty_label='El profesor general',
            )
        self.aplicar_estilo()

    # --- para la plantilla ------------------------------------------------------------------
    def grados_por_nivel(self):
        """[{nombre, clave, filas: [{grado, casilla, profesor (campo por grado)}]}] en orden escolar."""
        casillas = {str(casilla.data['value']): casilla for casilla in self['grados']}
        niveles = []
        for grado in self.grados_disponibles:
            if not niveles or niveles[-1]['clave'] != grado.nivel:
                niveles.append({'clave': grado.nivel, 'nombre': grado.get_nivel_display(), 'filas': []})
            niveles[-1]['filas'].append({'grado': grado, 'casilla': casillas.get(str(grado.pk)), 'profesor': self[f'profesor_{grado.pk}']})
        return niveles

    @property
    def origen_actual(self):
        return self['origen'].value() or 'existente'

    # --- validación ---------------------------------------------------------------------------
    def clean_nueva_nombre(self):
        return compactar_espacios(self.cleaned_data.get('nueva_nombre'))

    def clean(self):
        from Materias.forms import MateriaForm

        datos = super().clean()
        if datos.get('origen') == 'nueva':
            nueva = MateriaForm({'clave': datos.get('nueva_clave', ''), 'nombre': datos.get('nueva_nombre', '')})
            if nueva.is_valid():
                self.materia_nueva = nueva
            else:
                for campo, destino in (('nombre', 'nueva_nombre'), ('clave', 'nueva_clave')):
                    for error in nueva.errors.get(campo, []):
                        self.add_error(destino, error)
        elif not datos.get('materia'):
            self.add_error('materia', 'Elige la materia o crea una nueva.')
        return datos

    def profesor_de(self, grado):
        """El profesor elegido para ese grado (el de su fila si se eligió uno por grado; si no, el general)."""
        if not self.puede_asignar_profesores:
            return None
        if self.cleaned_data.get('por_grado'):
            return self.cleaned_data.get(f'profesor_{grado.pk}') or self.cleaned_data.get('profesor')
        return self.cleaned_data.get('profesor')

    # --- guardado ---------------------------------------------------------------------------
    def guardar(self):
        """Crea la materia (si es nueva), la pone en el plan de los grados y les asigna profesor.

        Devuelve {materia, ciclo, plan: {id de grado: (asignación, estado)}, cambios, omitidas, nueva}.
        """
        from django.db import transaction

        from Alumnos.docentes import agregar_al_plan, asignar_profesor

        ciclo = self.cleaned_data['ciclo']
        grados = sorted(self.cleaned_data['grados'], key=lambda grado: (self.grados_disponibles.index(grado)
                                                                         if grado in self.grados_disponibles else 99))
        cambios, omitidas = [], []
        with transaction.atomic():
            nueva = getattr(self, 'materia_nueva', None)
            materia = nueva.save() if nueva is not None else self.cleaned_data['materia']
            plan = agregar_al_plan(ciclo, materia, grados)
            por_profesor = {}
            for grado in grados:
                profesor = self.profesor_de(grado)
                if profesor is not None:
                    por_profesor.setdefault(profesor, []).append(plan[grado.pk][0])
            for profesor, asignaciones in por_profesor.items():
                hechos, fallidos = asignar_profesor(asignaciones, profesor)
                cambios += hechos
                omitidas += fallidos
        return {'materia': materia, 'ciclo': ciclo, 'plan': plan, 'cambios': cambios, 'omitidas': omitidas, 'nueva': nueva is not None}


class FiltroCargaForm(EstiloCamposMixin, forms.Form):
    """Filtros de la carga por profesor: texto, estado de la carga y orden."""

    ESTADO_CHOICES = [
        ('', 'Cualquier carga'),
        ('sobrecarga', 'Sobrecargados'),
        ('completa', 'Carga completa'),
        ('con_carga', 'Con carga'),
        ('libre', 'Sin clases'),
    ]
    ORDEN_CHOICES = [
        ('nombre', 'Nombre (A-Z)'),
        ('-carga', 'Más carga primero'),
        ('carga', 'Menos carga primero'),
    ]

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre o especialidad…', 'autocomplete': 'off',
    }))
    estado = forms.ChoiceField(required=False, choices=ESTADO_CHOICES, label='Carga')
    orden = forms.ChoiceField(required=False, choices=ORDEN_CHOICES, label='Ordenar por')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    @property
    def activos(self):
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}

    def filtrar(self, cargas):
        """Filtra y ordena las cargas que devuelve `carga_de_profesores` (una lista pequeña: se hace en Python)."""
        datos = self.activos

        palabras = [palabra.lower() for palabra in datos.get('q', '').split()]
        if palabras:
            cargas = [
                carga for carga in cargas
                if all(palabra in f'{carga["profesor"]} {carga["profesor"].especialidad}'.lower() for palabra in palabras)
            ]

        estado = datos.get('estado')
        if estado == 'con_carga':
            cargas = [carga for carga in cargas if carga['estado'] in ('normal', 'sin_limite')]
        elif estado:
            cargas = [carga for carga in cargas if carga['estado'] == estado]

        orden = datos.get('orden')
        if orden in ('carga', '-carga'):
            cargas = sorted(cargas, key=lambda carga: carga['minutos'], reverse=orden == '-carga')
        return cargas
