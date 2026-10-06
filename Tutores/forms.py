from django import forms
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q

from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Alumno, Tutor, TutorAlumno
from Alumnos.utils import CURP_RE, compactar_espacios, normalizar_curp, validar_telefono
from Alumnos.vinculos import sincronizar_principales

CHIP = forms.CheckboxInput(attrs={'class': 'choice__input'})


def vinculos_con_alumnos_vigentes():
    """Subconsulta: vínculos activos del tutor con alumnos que no están dados de baja."""
    return TutorAlumno.objects.filter(tutor=OuterRef('pk'), activo=True).exclude(alumno__estatus='BAJA')


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
class TutorForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = Tutor
        fields = [
            'nombre', 'apellido_paterno', 'apellido_materno', 'curp', 'estado_civil', 'religion',
            'telefono', 'telefono_alternativo', 'correo_electronico',
            'domicilio', 'colonia', 'ciudad', 'estado', 'cp',
            'ocupacion', 'lugar_trabajo', 'telefono_trabajo',
            'observaciones', 'estatus',
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'autocomplete': 'off', 'autofocus': True}),
            'apellido_paterno': forms.TextInput(attrs={'autocomplete': 'off'}),
            'apellido_materno': forms.TextInput(attrs={'autocomplete': 'off'}),
            'curp': forms.TextInput(attrs={
                'maxlength': 18, 'placeholder': 'Opcional', 'autocapitalize': 'characters',
                'autocomplete': 'off', 'spellcheck': 'false', 'data-curp-optional': '',
            }),
            'religion': forms.TextInput(attrs={'autocomplete': 'off'}),
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
            'ocupacion': forms.TextInput(attrs={'autocomplete': 'off'}),
            'lugar_trabajo': forms.TextInput(attrs={'autocomplete': 'off'}),
            'telefono_trabajo': forms.TextInput(attrs={'inputmode': 'tel', 'autocomplete': 'off', 'placeholder': 'Con extensión, si aplica'}),
            'observaciones': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Notas internas sobre este tutor'}),
        }
        help_texts = {
            'curp': 'Opcional. Si la capturas, debe ser única entre los tutores.',
            'telefono': 'Es el número principal de contacto.',
            'correo_electronico': 'Opcional.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = self.instance._state.adding
        self.fields['estado_civil'].choices = [('', 'Sin especificar'), *Tutor.ESTADO_CIVIL_CHOICES]
        if self.creando:
            del self.fields['estatus']  # nace como "Activo" (valor por defecto del modelo)
        self.aplicar_estilo()

    # --- limpieza por campo ----------------------------------------------------------
    def _compacto(self, campo):
        return compactar_espacios(self.cleaned_data.get(campo))

    def clean_nombre(self):
        return self._compacto('nombre')

    def clean_apellido_paterno(self):
        return self._compacto('apellido_paterno')

    def clean_apellido_materno(self):
        return self._compacto('apellido_materno')

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

    def clean_ocupacion(self):
        return self._compacto('ocupacion')

    def save(self, commit=True):
        with transaction.atomic():
            tutor = super().save(commit)
            if commit and 'estatus' in self.changed_data:
                sincronizar_principales(tutor)  # igual que al dar de baja o reactivar desde el perfil
        return tutor


# ---------------------------------------------------------------------------
# Listado: filtros
# ---------------------------------------------------------------------------
class FiltroTutoresForm(EstiloCamposMixin, forms.Form):
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
        ('con_alumnos', 'Con estudiantes vigentes'),
        ('sin_alumnos', 'Sin estudiantes vigentes'),
    ]

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre, teléfono, CURP o estudiante…', 'autocomplete': 'off',
    }))
    estatus = forms.ChoiceField(required=False, choices=[('', 'Activos'), *Tutor.ESTATUS_CHOICES], label='Estatus')
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

    def filtrar(self, queryset):
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
                | Q(ocupacion__icontains=palabra)
                | Q(alumnos_relacionados__alumno__nombre__icontains=palabra)
                | Q(alumnos_relacionados__alumno__apellido_paterno__icontains=palabra)
                | Q(alumnos_relacionados__alumno__apellido_materno__icontains=palabra)
                | Q(alumnos_relacionados__alumno__referencia__icontains=palabra)
            )

        # Las bajas no aparecen salvo que se pida ese estatus.
        queryset = queryset.filter(estatus=datos.get('estatus') or 'ACTIVO')

        situacion = datos.get('situacion')
        if situacion == 'con_alumnos':
            queryset = queryset.filter(Exists(vinculos_con_alumnos_vigentes()))
        elif situacion == 'sin_alumnos':
            queryset = queryset.filter(~Exists(vinculos_con_alumnos_vigentes()))

        return queryset.distinct().order_by(*self.ORDENES[datos.get('orden', 'nombre')])


# ---------------------------------------------------------------------------
# Vincular un alumno desde el perfil del tutor
# ---------------------------------------------------------------------------
class VinculoForm(EstiloCamposMixin, forms.Form):
    """Crea o actualiza el vínculo del tutor con un alumno."""

    alumno = forms.ModelChoiceField(
        Alumno.objects.all(),
        widget=forms.HiddenInput,
        error_messages={'required': 'Busca y elige un estudiante.', 'invalid_choice': 'Elige un estudiante de la lista.'},
    )
    parentesco = forms.ChoiceField(
        choices=[('', 'Selecciona…'), *TutorAlumno.PARENTESCO_CHOICES],
        label='Parentesco',
        error_messages={'required': 'Indica el parentesco.'},
    )
    tutor_principal = forms.BooleanField(required=False, label='Tutor principal', widget=CHIP)
    contacto_emergencia = forms.BooleanField(required=False, label='Contacto de emergencia', widget=CHIP)
    autorizado_recoger = forms.BooleanField(required=False, label='Puede recoger al estudiante', widget=CHIP)
    recibe_notificaciones = forms.BooleanField(required=False, initial=True, label='Recibe notificaciones', widget=CHIP)
    responsable_pagos = forms.BooleanField(required=False, label='Responsable de pagos', widget=CHIP)
    activo = forms.BooleanField(required=False, initial=True, label='Vínculo activo', widget=CHIP)
    observaciones = forms.CharField(required=False, label='Observaciones', widget=forms.Textarea(attrs={'rows': 2}))

    CAMPOS = (
        'parentesco', 'tutor_principal', 'contacto_emergencia', 'autorizado_recoger',
        'recibe_notificaciones', 'responsable_pagos', 'observaciones', 'activo',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def guardar(self, tutor):
        """Crea o actualiza el vínculo; devuelve (vínculo, creado)."""
        datos = self.cleaned_data
        alumno = datos['alumno']
        valores = {campo: datos[campo] for campo in self.CAMPOS}

        otro_principal = (
            TutorAlumno.objects.filter(alumno=alumno, activo=True, tutor_principal=True, tutor__estatus='ACTIVO')
            .exclude(tutor=tutor).exists()
        )
        if valores['activo'] and not otro_principal:
            valores['tutor_principal'] = True  # todo alumno con tutores vigentes tiene un principal
        if not valores['activo']:
            valores['tutor_principal'] = False

        vinculo, creado = TutorAlumno.objects.update_or_create(tutor=tutor, alumno=alumno, defaults=valores)
        if vinculo.tutor_principal:
            TutorAlumno.objects.filter(alumno=alumno).exclude(pk=vinculo.pk).update(tutor_principal=False)
        return vinculo, creado
