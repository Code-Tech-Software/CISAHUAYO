from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import MateriaGrado, Profesor
from Alumnos.utils import CURP_RE, compactar_espacios, normalizar_curp, validar_telefono

EDAD_MINIMA = 18
MAXIMO_DE_HORAS = 60   # horas de clase por semana: más no cabe en una semana de trabajo


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
class ProfesorForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición. La baja y la reactivación son acciones aparte (no hay borrado físico)."""

    class Meta:
        model = Profesor
        fields = [
            'nombre', 'apellido_paterno', 'apellido_materno', 'curp', 'fecha_nacimiento',
            'telefono', 'telefono_alternativo', 'correo_electronico',
            'domicilio', 'colonia', 'ciudad', 'estado', 'cp',
            'profesion', 'cedula_profesional', 'especialidad', 'fecha_ingreso', 'horas_maximas',
            'observaciones',
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'autocomplete': 'off', 'autofocus': True}),
            'apellido_paterno': forms.TextInput(attrs={'autocomplete': 'off'}),
            'apellido_materno': forms.TextInput(attrs={'autocomplete': 'off'}),
            'curp': forms.TextInput(attrs={
                'maxlength': 18, 'placeholder': 'Opcional', 'autocapitalize': 'characters',
                'autocomplete': 'off', 'spellcheck': 'false', 'data-curp-optional': '',
            }),
            'fecha_nacimiento': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'telefono': forms.TextInput(attrs={'inputmode': 'tel', 'autocomplete': 'off', 'placeholder': '10 dígitos', 'data-phone': ''}),
            'telefono_alternativo': forms.TextInput(attrs={'inputmode': 'tel', 'autocomplete': 'off', 'placeholder': 'Opcional', 'data-phone': ''}),
            'correo_electronico': forms.EmailInput(attrs={'autocomplete': 'off', 'placeholder': 'Opcional'}),
            'domicilio': forms.TextInput(attrs={'autocomplete': 'street-address', 'placeholder': 'Calle y número'}),
            'colonia': forms.TextInput(attrs={'autocomplete': 'off'}),
            'ciudad': forms.TextInput(attrs={'autocomplete': 'address-level2'}),
            'estado': forms.TextInput(attrs={'list': 'estados-mx', 'autocomplete': 'address-level1'}),
            'cp': forms.TextInput(attrs={
                'inputmode': 'numeric', 'maxlength': 5, 'pattern': r'\d{5}',
                'placeholder': '5 dígitos', 'autocomplete': 'postal-code',
            }),
            'profesion': forms.TextInput(attrs={'autocomplete': 'off', 'placeholder': 'Licenciatura en Educación Primaria'}),
            'cedula_profesional': forms.TextInput(attrs={'autocomplete': 'off', 'maxlength': 20, 'placeholder': 'Opcional', 'inputmode': 'numeric'}),
            'especialidad': forms.TextInput(attrs={'autocomplete': 'off', 'placeholder': 'Matemáticas, inglés, educación física…'}),
            'horas_maximas': forms.NumberInput(attrs={'min': 1, 'max': MAXIMO_DE_HORAS, 'inputmode': 'numeric', 'placeholder': 'Sin tope'}),
            'fecha_ingreso': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'observaciones': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Notas internas sobre este profesor'}),
        }
        help_texts = {
            'curp': 'Opcional. Si la capturas, debe ser única entre los profesores.',
            'telefono': 'Es el número principal de contacto.',
            'correo_electronico': 'Opcional. Debe ser único entre los profesores.',
            'especialidad': 'Opcional. Sirve de referencia al elegir quién imparte cada materia.',
            'horas_maximas': 'Opcional. Las horas de clase por semana que puede dar como máximo: en «Asignaciones» se avisa si su carga la rebasa.',
        }

    def __init__(self, *args, actor=None, abrir_acceso=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()
        # «Dar acceso al sistema»: su cuenta de usuario (nueva o una que ya existe), anidada con el prefijo «acceso»
        self.acceso = None
        if actor is not None:
            from Usuarios.forms import CuentaDeProfesorForm
            self.acceso = CuentaDeProfesorForm(
                self.data or None, prefix='acceso', actor=actor, profesor=self.instance if self.instance.pk else None,
                initial={'dar_acceso': abrir_acceso},
            )
        self.cuenta = self.contrasena_en_claro = None
        self.cuenta_nueva = False

    def is_valid(self):
        propio = super().is_valid()
        anidado = self.acceso.is_valid() if self.acceso is not None else True
        return propio and anidado

    def save(self, commit=True):
        from django.db import transaction

        from Usuarios.docentes import sincronizar_nombre

        with transaction.atomic():
            profesor = super().save(commit)
            sincronizar_nombre(profesor)   # la cuenta lleva el nombre de la ficha
            if self.acceso is not None:
                self.cuenta, self.contrasena_en_claro, self.cuenta_nueva = self.acceso.guardar(profesor)
        return profesor

    # --- limpieza por campo ----------------------------------------------------------
    def _compacto(self, campo):
        return compactar_espacios(self.cleaned_data.get(campo))

    def clean_nombre(self):
        return self._compacto('nombre')

    def clean_apellido_paterno(self):
        return self._compacto('apellido_paterno')

    def clean_apellido_materno(self):
        return self._compacto('apellido_materno')

    def clean_profesion(self):
        return self._compacto('profesion')

    def clean_especialidad(self):
        return self._compacto('especialidad')

    def clean_cedula_profesional(self):
        return self._compacto('cedula_profesional').upper()

    def clean_curp(self):
        curp = normalizar_curp(self.cleaned_data.get('curp'))
        if not curp:
            return None  # el campo es único: vacío se guarda como NULL, no como ''
        if not CURP_RE.match(curp):
            raise ValidationError('La CURP no tiene un formato válido. Revisa que sean 18 caracteres.')
        return curp

    def clean_telefono(self):
        return validar_telefono(self.cleaned_data.get('telefono'))

    def clean_telefono_alternativo(self):
        telefono = self.cleaned_data.get('telefono_alternativo')
        return validar_telefono(telefono) if telefono else ''

    def clean_correo_electronico(self):
        correo = (self.cleaned_data.get('correo_electronico') or '').strip().lower()
        return correo or None

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data.get('fecha_nacimiento')
        if fecha:
            hoy = timezone.localdate()
            if fecha > hoy:
                raise ValidationError('La fecha de nacimiento no puede ser futura.')
            if fecha > hoy - timedelta(days=365 * EDAD_MINIMA + 4):
                raise ValidationError(f'Un profesor debe tener al menos {EDAD_MINIMA} años.')
        return fecha

    def clean_horas_maximas(self):
        horas = self.cleaned_data.get('horas_maximas')
        if horas is not None and not 1 <= horas <= MAXIMO_DE_HORAS:
            raise ValidationError(f'Escribe de 1 a {MAXIMO_DE_HORAS} horas por semana.')
        return horas

    def clean_fecha_ingreso(self):
        fecha = self.cleaned_data.get('fecha_ingreso')
        if fecha and fecha > timezone.localdate():
            raise ValidationError('La fecha de ingreso no puede ser futura.')
        return fecha


# ---------------------------------------------------------------------------
# Listado: filtros
# ---------------------------------------------------------------------------
class FiltroProfesoresForm(EstiloCamposMixin, forms.Form):
    ORDENES = {
        'nombre': ('apellido_paterno', 'apellido_materno', 'nombre'),
        '-nombre': ('-apellido_paterno', '-apellido_materno', '-nombre'),
        '-reciente': ('-creado', 'apellido_paterno'),
        'antiguo': ('creado', 'apellido_paterno'),
    }
    ORDEN_CHOICES = [
        ('nombre', 'Nombre (A-Z)'),
        ('-nombre', 'Nombre (Z-A)'),
        ('-reciente', 'Registro más reciente'),
        ('antiguo', 'Registro más antiguo'),
    ]
    SITUACION_CHOICES = [
        ('', 'Cualquier situación'),
        ('con_materias', 'Con materias en el ciclo actual'),
        ('sin_materias', 'Sin materias en el ciclo actual'),
    ]

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre, teléfono, correo, especialidad o materia…', 'autocomplete': 'off',
    }))
    estatus = forms.ChoiceField(required=False, choices=[('', 'Activos'), *Profesor.ESTATUS_CHOICES], label='Estatus')
    situacion = forms.ChoiceField(required=False, choices=SITUACION_CHOICES, label='Situación')
    orden = forms.ChoiceField(required=False, choices=ORDEN_CHOICES, label='Ordenar por')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    @property
    def activos(self):
        """Valores válidos de los filtros (los inválidos de la URL se ignoran)."""
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}

    def filtrar(self, queryset, ciclo=None, con_estatus=True):
        datos = self.activos

        for palabra in datos.get('q', '').split():
            queryset = queryset.filter(
                Q(nombre__icontains=palabra)
                | Q(apellido_paterno__icontains=palabra)
                | Q(apellido_materno__icontains=palabra)
                | Q(curp__icontains=palabra)
                | Q(telefono__icontains=palabra)
                | Q(telefono_alternativo__icontains=palabra)
                | Q(correo_electronico__icontains=palabra)
                | Q(profesion__icontains=palabra)
                | Q(especialidad__icontains=palabra)
                | Q(cedula_profesional__icontains=palabra)
                | Q(asignaciones__materia__nombre__icontains=palabra)
                | Q(asignaciones__materia__clave__icontains=palabra)
                | Q(habilitaciones__materia__nombre__icontains=palabra)
                | Q(habilitaciones__materia__clave__icontains=palabra)
            )

        # Las bajas no aparecen salvo que se pida ese estatus.
        if con_estatus:
            queryset = queryset.filter(estatus=datos.get('estatus') or 'ACTIVO')

        situacion = datos.get('situacion')
        if situacion:
            con_materias = Exists(
                MateriaGrado.objects.filter(profesor=OuterRef('pk'), ciclo=ciclo, activa=True)
                if ciclo else MateriaGrado.objects.none()
            )
            queryset = queryset.filter(con_materias if situacion == 'con_materias' else ~con_materias)

        return queryset.distinct().order_by(*self.ORDENES[datos.get('orden', 'nombre')])
