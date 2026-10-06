from django import forms
from django.db.models import Exists, OuterRef, Q

from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Grado, HorarioMateria, Profesor, ProfesorMateria


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
