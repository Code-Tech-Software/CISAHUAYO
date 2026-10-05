from django import forms
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q
from django.utils import timezone

from .academico import ciclo_actual as ciclo_activo, motivo_no_inscribible
from .models import Alumno, CicloEscolar, Grado, Inscripcion, Tutor, TutorAlumno
from .utils import (
    CURP_RE,
    compactar_espacios as _compactar,
    generar_contrasena,
    normalizar_curp,
    siguiente_referencia,
    validar_telefono,
)

TAMANO_MAXIMO_FOTO = 5 * 1024 * 1024  # 5 MB
LARGO_MINIMO_CONTRASENA = 6


class EstiloCamposMixin:
    """Aplica la clase del sistema de diseño (.field__control) a los widgets de texto."""

    def aplicar_estilo(self):
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, (forms.HiddenInput, forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect, forms.FileInput)):
                continue
            clases = ['field__control']
            if isinstance(widget, forms.Select):
                clases.append('field__control--select')
            widget.attrs['class'] = ' '.join(filter(None, [widget.attrs.get('class'), *clases]))


# ---------------------------------------------------------------------------
# Alumno
# ---------------------------------------------------------------------------
class AlumnoForm(EstiloCamposMixin, forms.ModelForm):
    """Datos del alumno. Se usa en el asistente de registro y en la edición.

    La contraseña (`contrasena`) nunca se edita aquí: al registrar se guarda cifrada
    a partir de `contrasena_inicial`, y después solo se restablece desde el perfil.
    """

    quitar_fotografia = forms.BooleanField(required=False, label='Quitar fotografía')
    contrasena_inicial = forms.CharField(
        required=False,
        max_length=64,
        label='Contraseña de acceso',
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'spellcheck': 'false', 'class': 'field__control--mono'}),
        help_text='Se guarda cifrada. Si la dejas vacía se genera una automáticamente.',
    )

    class Meta:
        model = Alumno
        fields = [
            'fotografia', 'nombre', 'apellido_paterno', 'apellido_materno', 'curp',
            'fecha_nacimiento', 'sexo', 'nacionalidad', 'religion',
            'domicilio', 'colonia', 'ciudad', 'estado', 'cp',
            'grupo_sanguineo', 'alergias', 'observaciones_generales',
            'fecha_ingreso', 'escuela_procedencia', 'referencia', 'uid',
            'correo_electronico', 'estatus',
        ]
        widgets = {
            'fotografia': forms.FileInput(attrs={'accept': 'image/*', 'class': 'photo-field__input visually-hidden'}),
            'nombre': forms.TextInput(attrs={'autocomplete': 'off', 'autofocus': True}),
            'apellido_paterno': forms.TextInput(attrs={'autocomplete': 'off'}),
            'apellido_materno': forms.TextInput(attrs={'autocomplete': 'off'}),
            'curp': forms.TextInput(attrs={
                'maxlength': 18, 'placeholder': '18 caracteres', 'autocapitalize': 'characters',
                'autocomplete': 'off', 'spellcheck': 'false', 'data-curp': '',
            }),
            'fecha_nacimiento': forms.DateInput(attrs={'type': 'date', 'data-fecha-nacimiento': ''}, format='%Y-%m-%d'),
            'fecha_ingreso': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'sexo': forms.RadioSelect(attrs={'class': 'choice__input'}),
            'grupo_sanguineo': forms.RadioSelect(attrs={'class': 'choice__input'}),
            'religion': forms.TextInput(attrs={'autocomplete': 'off'}),
            'domicilio': forms.TextInput(attrs={'autocomplete': 'street-address', 'placeholder': 'Calle y número'}),
            'colonia': forms.TextInput(attrs={'autocomplete': 'off'}),
            'ciudad': forms.TextInput(attrs={'autocomplete': 'address-level2'}),
            'estado': forms.TextInput(attrs={'list': 'estados-mx', 'autocomplete': 'address-level1'}),
            'cp': forms.TextInput(attrs={
                'inputmode': 'numeric', 'maxlength': 5, 'pattern': r'\d{5}',
                'placeholder': '5 dígitos', 'autocomplete': 'postal-code',
            }),
            'alergias': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Alergias, padecimientos o medicamentos que debamos conocer'}),
            'observaciones_generales': forms.Textarea(attrs={'rows': 3}),
            'escuela_procedencia': forms.TextInput(attrs={'autocomplete': 'off'}),
            'referencia': forms.TextInput(attrs={'autocomplete': 'off', 'spellcheck': 'false', 'class': 'field__control--mono'}),
            'uid': forms.TextInput(attrs={'autocomplete': 'off', 'spellcheck': 'false', 'placeholder': 'Opcional'}),
            'correo_electronico': forms.EmailInput(attrs={'autocomplete': 'off', 'placeholder': 'Opcional'}),
        }
        help_texts = {
            'fotografia': 'JPG o PNG de hasta 5 MB.',
            'curp': 'Al escribirla completamos la fecha de nacimiento y el sexo.',
            'referencia': 'Código único del alumno: es el que se escanea para pasar asistencia.',
            'uid': 'Número de la tarjeta, si el alumno la usa.',
            'correo_electronico': 'Debe ser único entre los alumnos.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = self.instance._state.adding

        # Sexo y grupo sanguíneo van como opciones visibles: sin la opción en blanco.
        self.fields['sexo'].choices = Alumno.SEXO_CHOICES
        self.fields['grupo_sanguineo'].choices = Alumno.GRUPO_SANGUINEO_CHOICES

        if self.creando:
            del self.fields['estatus']  # nace como "Activo" (valor por defecto del modelo)
            if not self.is_bound:
                self.initial.setdefault('referencia', siguiente_referencia())
                self.initial.setdefault('ciudad', 'Sahuayo')
                self.initial.setdefault('estado', 'Michoacán')
                self.fields['contrasena_inicial'].initial = generar_contrasena()
        else:
            del self.fields['contrasena_inicial']
        self.aplicar_estilo()

    # --- limpieza por campo --------------------------------------------------
    def _texto_compacto(self, nombre_campo):
        return _compactar(self.cleaned_data.get(nombre_campo))

    def clean_nombre(self):
        return self._texto_compacto('nombre')

    def clean_apellido_paterno(self):
        return self._texto_compacto('apellido_paterno')

    def clean_apellido_materno(self):
        return self._texto_compacto('apellido_materno')

    def clean_curp(self):
        curp = normalizar_curp(self.cleaned_data.get('curp'))
        if not CURP_RE.match(curp):
            raise ValidationError('La CURP no tiene un formato válido. Revisa que sean 18 caracteres.')
        return curp

    def clean_referencia(self):
        return (self.cleaned_data.get('referencia') or '').strip()

    def clean_correo_electronico(self):
        correo = (self.cleaned_data.get('correo_electronico') or '').strip().lower()
        return correo or None

    def clean_fecha_nacimiento(self):
        nacimiento = self.cleaned_data.get('fecha_nacimiento')
        if nacimiento and nacimiento > timezone.localdate():
            raise ValidationError('La fecha de nacimiento no puede ser futura.')
        return nacimiento

    def clean_fotografia(self):
        foto = self.cleaned_data.get('fotografia')
        if isinstance(foto, UploadedFile) and foto.size > TAMANO_MAXIMO_FOTO:
            raise ValidationError('La fotografía no debe pesar más de 5 MB.')
        return foto

    def clean_contrasena_inicial(self):
        contrasena = self.cleaned_data.get('contrasena_inicial', '')
        if contrasena and len(contrasena) < LARGO_MINIMO_CONTRASENA:
            raise ValidationError(f'Usa al menos {LARGO_MINIMO_CONTRASENA} caracteres.')
        return contrasena

    # --- guardado --------------------------------------------------------------
    def save(self, commit=True):
        alumno = super().save(commit=False)
        if self.cleaned_data.get('quitar_fotografia') and 'fotografia' not in self.files:
            alumno.fotografia = None
        self.contrasena_en_claro = None
        if self.creando:
            self.contrasena_en_claro = self.cleaned_data.get('contrasena_inicial') or generar_contrasena()
            alumno.contrasena = make_password(self.contrasena_en_claro)
        if commit:
            alumno.save()
        return alumno


# ---------------------------------------------------------------------------
# Tutores del alumno (vínculo con un tutor existente o alta de uno nuevo)
# ---------------------------------------------------------------------------
class TutorVinculoForm(EstiloCamposMixin, forms.Form):
    MODOS = (('nuevo', 'Nuevo'), ('existente', 'Existente'))

    # Control interno
    vinculo_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    modo = forms.ChoiceField(choices=MODOS, initial='nuevo', widget=forms.HiddenInput)
    tutor = forms.ModelChoiceField(Tutor.objects.all(), required=False, widget=forms.HiddenInput)

    # Datos del tutor nuevo
    nombre = forms.CharField(max_length=80, required=False, label='Nombre(s)')
    apellido_paterno = forms.CharField(max_length=60, required=False, label='Apellido paterno')
    apellido_materno = forms.CharField(max_length=60, required=False, label='Apellido materno')
    telefono = forms.CharField(max_length=20, required=False, label='Teléfono celular')
    correo_electronico = forms.EmailField(max_length=254, required=False, label='Correo electrónico')
    curp = forms.CharField(max_length=18, required=False, label='CURP')
    ocupacion = forms.CharField(max_length=100, required=False, label='Ocupación')
    mismo_domicilio = forms.BooleanField(required=False, initial=True, label='Vive en el mismo domicilio del alumno', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))

    # Relación con el alumno
    parentesco = forms.ChoiceField(
        choices=[('', 'Selecciona…'), *TutorAlumno.PARENTESCO_CHOICES],
        required=False,
        label='Parentesco',
    )
    tutor_principal = forms.BooleanField(required=False, label='Tutor principal', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))
    contacto_emergencia = forms.BooleanField(required=False, label='Contacto de emergencia', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))
    autorizado_recoger = forms.BooleanField(required=False, label='Puede recoger al alumno', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))
    recibe_notificaciones = forms.BooleanField(required=False, initial=True, label='Recibe notificaciones', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))
    responsable_pagos = forms.BooleanField(required=False, label='Responsable de pagos', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))
    observaciones = forms.CharField(required=False, label='Observaciones', widget=forms.Textarea(attrs={'rows': 2}))
    activo = forms.BooleanField(required=False, initial=True, label='Vínculo activo', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tutor_existente = None
        # Marcas para la validación por paso del asistente (static/js/alumnos-form.js)
        for campo in ('nombre', 'apellido_paterno', 'telefono'):
            self.fields[campo].widget.attrs['data-required-new'] = ''
        self.fields['parentesco'].widget.attrs['data-required'] = ''
        self.fields['telefono'].widget.attrs.update({'inputmode': 'tel', 'autocomplete': 'off', 'placeholder': '10 dígitos', 'data-phone': ''})
        self.fields['curp'].widget.attrs.update({'autocapitalize': 'characters', 'placeholder': 'Opcional', 'spellcheck': 'false', 'data-curp-optional': ''})
        self.fields['correo_electronico'].widget.attrs.update({'placeholder': 'Opcional'})
        self.aplicar_estilo()

    @property
    def tutor_existente(self):
        """El Tutor elegido (para mostrar su resumen), o None."""
        if self._tutor_existente is None:
            pk = self['tutor'].value()
            if pk:
                self._tutor_existente = Tutor.objects.filter(pk=pk).first() or False
        return self._tutor_existente or None

    # --- limpieza -----------------------------------------------------------------
    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono')
        return validar_telefono(telefono) if telefono else ''

    def clean_curp(self):
        curp = normalizar_curp(self.cleaned_data.get('curp'))
        if curp and not CURP_RE.match(curp):
            raise ValidationError('La CURP no tiene un formato válido.')
        return curp

    def clean(self):
        datos = super().clean()

        if datos.get('modo') == 'existente':
            if not datos.get('tutor') and 'tutor' not in self.errors:
                self.add_error('tutor', 'Selecciona un tutor de la lista.')
        else:
            for campo, etiqueta in (('nombre', 'el nombre'), ('apellido_paterno', 'el apellido paterno'), ('telefono', 'el teléfono')):
                if not datos.get(campo) and campo not in self.errors:
                    self.add_error(campo, f'Escribe {etiqueta} del tutor.')
            for campo in ('nombre', 'apellido_paterno', 'apellido_materno', 'ocupacion'):
                if datos.get(campo):
                    datos[campo] = _compactar(datos[campo])
            curp = datos.get('curp')
            if curp and 'curp' not in self.errors:
                existente = Tutor.objects.filter(curp=curp).first()
                if existente:
                    self.add_error('curp', f'Ya existe un tutor con esta CURP: {existente}. Búscalo para vincularlo.')

        if not datos.get('parentesco') and 'parentesco' not in self.errors:
            self.add_error('parentesco', 'Indica el parentesco.')
        return datos


class BaseTutoresFormSet(forms.BaseFormSet):
    """Reglas entre tutores: sin repetidos, un solo principal y, al registrar, al menos uno."""

    requiere_tutor = False

    def vinculos_validos(self):
        """Formularios con datos que no están marcados para eliminarse."""
        return [
            form for form in self.forms
            if getattr(form, 'cleaned_data', None) and not self._should_delete_form(form)
        ]

    def clean(self):
        if any(self.errors):
            return
        vigentes = self.vinculos_validos()

        if self.requiere_tutor and not vigentes:
            raise ValidationError('Agrega al menos un tutor: busca uno existente o crea uno nuevo.')

        ids = [f.cleaned_data['tutor'].pk for f in vigentes if f.cleaned_data.get('modo') == 'existente']
        if len(ids) != len(set(ids)):
            raise ValidationError('Un mismo tutor no puede agregarse dos veces.')

        curps = [f.cleaned_data['curp'] for f in vigentes if f.cleaned_data.get('modo') == 'nuevo' and f.cleaned_data.get('curp')]
        if len(curps) != len(set(curps)):
            raise ValidationError('Dos de los tutores nuevos tienen la misma CURP.')

        # Un vínculo inactivo no puede ser el principal: solo cuentan los vigentes.
        activos = [f for f in vigentes if f.cleaned_data.get('activo')]
        for form in vigentes:
            if form not in activos:
                form.cleaned_data['tutor_principal'] = False
        principales = [f for f in activos if f.cleaned_data.get('tutor_principal')]
        if len(principales) > 1:
            raise ValidationError('Solo puede haber un tutor principal.')
        if activos and not principales:
            activos[0].cleaned_data['tutor_principal'] = True  # el primero queda como principal


TutoresFormSet = forms.formset_factory(
    TutorVinculoForm,
    formset=BaseTutoresFormSet,
    extra=0,
    can_delete=True,
)

CAMPOS_VINCULO = (
    'parentesco', 'tutor_principal', 'contacto_emergencia', 'autorizado_recoger',
    'recibe_notificaciones', 'responsable_pagos', 'observaciones', 'activo',
)


def iniciales_vinculos(alumno):
    """Datos iniciales del formset al editar: un formulario por vínculo existente."""
    vinculos = alumno.tutores_relacionados.select_related('tutor').order_by('-tutor_principal', 'tutor__apellido_paterno')
    return [
        {'vinculo_id': v.pk, 'modo': 'existente', 'tutor': v.tutor_id, **{c: getattr(v, c) for c in CAMPOS_VINCULO}}
        for v in vinculos
    ]


def guardar_vinculos(alumno, formset):
    """Crea o actualiza los vínculos del alumno. Llamar dentro de una transacción.

    Quitar un tutor del formulario es una baja lógica: el vínculo se conserva con
    activo=False (y deja de ser el principal), no se borra.
    """
    for form in formset.deleted_forms:
        vinculo_id = form.cleaned_data.get('vinculo_id')
        if vinculo_id:
            TutorAlumno.objects.filter(pk=vinculo_id, alumno=alumno).update(activo=False, tutor_principal=False)

    for form in formset.vinculos_validos():
        datos = form.cleaned_data
        if datos['modo'] == 'existente':
            tutor = datos['tutor']
        else:
            tutor = Tutor(
                nombre=datos['nombre'],
                apellido_paterno=datos['apellido_paterno'],
                apellido_materno=datos.get('apellido_materno', ''),
                telefono=datos['telefono'],
                correo_electronico=datos.get('correo_electronico') or None,
                curp=datos.get('curp') or None,
                ocupacion=datos.get('ocupacion', ''),
            )
            if datos.get('mismo_domicilio'):
                tutor.domicilio, tutor.colonia = alumno.domicilio, alumno.colonia
                tutor.ciudad, tutor.estado, tutor.cp = alumno.ciudad, alumno.estado, alumno.cp
            tutor.save()
        TutorAlumno.objects.update_or_create(
            tutor=tutor,
            alumno=alumno,
            defaults={campo: datos[campo] for campo in CAMPOS_VINCULO},
        )


# ---------------------------------------------------------------------------
# Inscripción
# ---------------------------------------------------------------------------
class CicloChoiceField(forms.ModelChoiceField):
    """Selector de ciclo que indica cuál es el actual, cuáles vienen y cuáles ya cerraron."""

    ETIQUETAS = {'ACTUAL': ' · actual', 'PROXIMO': ' · próximo', 'CERRADO': ' · cerrado'}

    def label_from_instance(self, ciclo):
        return f'{ciclo.nombre}{self.ETIQUETAS[ciclo.estado]}'


class GradoChoiceIterator(forms.models.ModelChoiceIterator):
    """Agrupa los grados por nivel (<optgroup>); el queryset debe venir en orden escolar."""

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ('', self.field.empty_label)
        grupos = {}
        for grado in self.queryset:
            grupos.setdefault(grado.get_nivel_display(), []).append(self.choice(grado))
        yield from grupos.items()


class GradoChoiceField(forms.ModelChoiceField):
    iterator = GradoChoiceIterator


def grados_disponibles(incluir=None):
    """Grados que se pueden elegir al inscribir: los activos (y `incluir`, aunque ya no lo esté), en orden escolar."""
    condicion = Q(activo=True)
    if incluir is not None:
        condicion |= Q(pk=incluir.pk)
    return Grado.objects.filter(condicion).academicos()


class InscripcionInicialForm(EstiloCamposMixin, forms.Form):
    """Inscripción opcional al registrar al alumno."""

    inscribir = forms.BooleanField(required=False, label='Inscribir al alumno ahora', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))
    ciclo = CicloChoiceField(CicloEscolar.objects.all(), required=False, empty_label='Selecciona un ciclo', label='Ciclo escolar')
    grado = GradoChoiceField(Grado.objects.none(), required=False, empty_label='Selecciona un grado', label='Grado')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['grado'].queryset = grados_disponibles()
        if not self.is_bound:
            self.fields['ciclo'].initial = ciclo_activo()
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        if datos.get('inscribir'):
            for campo, etiqueta in (('ciclo', 'el ciclo escolar'), ('grado', 'el grado')):
                if not datos.get(campo) and campo not in self.errors:
                    self.add_error(campo, f'Elige {etiqueta}.')
        return datos

    def guardar(self, alumno):
        datos = self.cleaned_data
        if datos.get('inscribir'):
            return Inscripcion.objects.create(alumno=alumno, ciclo=datos['ciclo'], grado=datos['grado'])
        return None


class InscribirForm(EstiloCamposMixin, forms.ModelForm):
    """Inscribir a un alumno que ya existe (desde su perfil)."""

    class Meta:
        model = Inscripcion
        fields = ['ciclo', 'grado', 'fecha_inscripcion']
        field_classes = {'ciclo': CicloChoiceField, 'grado': GradoChoiceField}
        widgets = {'fecha_inscripcion': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, alumno, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.alumno = alumno
        self.fields['ciclo'].empty_label = 'Selecciona un ciclo'
        self.fields['grado'].empty_label = 'Selecciona un grado'
        self.fields['grado'].queryset = grados_disponibles()
        if not self.is_bound:
            self.fields['ciclo'].initial = ciclo_activo()
        self.aplicar_estilo()

    def clean_fecha_inscripcion(self):
        fecha = self.cleaned_data['fecha_inscripcion']
        if fecha > timezone.localdate():
            raise ValidationError('La fecha de inscripción no puede ser futura.')
        return fecha

    def clean(self):
        datos = super().clean()
        motivo = motivo_no_inscribible(self.instance.alumno)
        if motivo:
            raise ValidationError(motivo)
        ciclo = datos.get('ciclo')
        # La restricción alumno+ciclo queda fuera de la validación del ModelForm (alumno no es campo).
        if ciclo and Inscripcion.objects.filter(alumno=self.instance.alumno, ciclo=ciclo).exists():
            raise ValidationError('El alumno ya está inscrito en este ciclo escolar.')
        return datos


# ---------------------------------------------------------------------------
# Listado: filtros
# ---------------------------------------------------------------------------
class FiltroAlumnosForm(EstiloCamposMixin, forms.Form):
    ORDENES = {
        'nombre': ('apellido_paterno', 'apellido_materno', 'nombre'),
        '-nombre': ('-apellido_paterno', '-apellido_materno', '-nombre'),
        '-ingreso': ('-fecha_ingreso', 'apellido_paterno'),
        'ingreso': ('fecha_ingreso', 'apellido_paterno'),
        'referencia': ('referencia',),
    }
    ORDEN_CHOICES = [
        ('nombre', 'Nombre (A-Z)'),
        ('-nombre', 'Nombre (Z-A)'),
        ('-ingreso', 'Ingreso más reciente'),
        ('ingreso', 'Ingreso más antiguo'),
        ('referencia', 'Referencia'),
    ]
    SITUACION_CHOICES = [
        ('', 'Cualquier situación'),
        ('inscritos', 'Inscritos en el ciclo actual'),
        ('sin_inscripcion', 'Sin inscripción en el ciclo actual'),
        ('sin_tutor', 'Sin tutor activo'),
    ]

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre, referencia, CURP o tutor…', 'autocomplete': 'off',
    }))
    estatus = forms.ChoiceField(required=False, choices=[('', 'Todos'), *Alumno.ESTATUS_CHOICES], label='Estatus')
    grado = GradoChoiceField(Grado.objects.academicos(), required=False, empty_label='Todos los grados', label='Grado actual')
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
                | Q(referencia__icontains=palabra)
                | Q(curp__icontains=palabra)
                | Q(uid__icontains=palabra)
                | Q(correo_electronico__icontains=palabra)
                | Q(tutores_relacionados__tutor__nombre__icontains=palabra)
                | Q(tutores_relacionados__tutor__apellido_paterno__icontains=palabra)
                | Q(tutores_relacionados__tutor__apellido_materno__icontains=palabra)
            )

        if datos.get('estatus'):
            queryset = queryset.filter(estatus=datos['estatus'])
        else:
            queryset = queryset.exclude(estatus='BAJA')  # las bajas se consultan en su propio filtro

        inscrito_actual = Q(inscripciones__activa=True, inscripciones__ciclo__activo=True)
        if datos.get('grado'):
            queryset = queryset.filter(inscrito_actual, inscripciones__grado=datos['grado'])

        situacion = datos.get('situacion')
        if situacion == 'inscritos':
            queryset = queryset.filter(inscrito_actual)
        elif situacion == 'sin_inscripcion':
            queryset = queryset.exclude(pk__in=Alumno.objects.filter(inscrito_actual).values('pk'))
        elif situacion == 'sin_tutor':
            queryset = queryset.exclude(
                pk__in=TutorAlumno.objects.filter(activo=True, tutor__estatus='ACTIVO').values('alumno_id'),
            )

        return queryset.distinct().order_by(*self.ORDENES[datos.get('orden', 'nombre')])
