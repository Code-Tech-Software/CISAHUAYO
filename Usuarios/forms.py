import re

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from Alumnos.forms import EstiloCamposMixin
from Alumnos.utils import compactar_espacios, validar_telefono

from .models import PerfilUsuario, Rol
from .seguridad import asignar_rol, contrasena_temporal, es_ultimo_administrador, nombre_de, rol_de, roles_asignables

Usuario = get_user_model()

NOMBRE_DE_USUARIO_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{2,29}$')
AYUDA_USUARIO = 'Con él inicia sesión. De 3 a 30 caracteres: minúsculas, números, punto, guion y guion bajo.'
AYUDA_CONTRASENA = 'Opcional. Si la dejas vacía se genera una temporal. En ambos casos deberá elegir una propia al entrar por primera vez.'


# ---------------------------------------------------------------------------
# Reglas de una cuenta (las comparten el alta de usuarios y «Dar acceso al sistema» de los profesores)
# ---------------------------------------------------------------------------
def validar_nombre_de_usuario(valor, cuenta=None):
    valor = (valor or '').strip()
    if cuenta is not None and cuenta.pk and valor == cuenta.username:
        return valor   # una cuenta que ya existía conserva su usuario aunque no cumpla la regla actual
    valor = valor.lower()
    if not NOMBRE_DE_USUARIO_RE.match(valor):
        raise ValidationError('Usa de 3 a 30 caracteres: minúsculas, números, punto, guion o guion bajo, empezando con letra o número.')
    repetido = Usuario.objects.filter(username__iexact=valor)
    if cuenta is not None and cuenta.pk:
        repetido = repetido.exclude(pk=cuenta.pk)
    if repetido.exists():
        raise ValidationError('Ya existe una cuenta con ese usuario.')
    return valor


def validar_correo_de_cuenta(correo, cuenta=None):
    correo = (correo or '').strip().lower()
    repetido = Usuario.objects.filter(email__iexact=correo)
    if cuenta is not None and cuenta.pk:
        repetido = repetido.exclude(pk=cuenta.pk)
    if correo and repetido.exists():
        raise ValidationError('Ya hay una cuenta con ese correo electrónico.')
    return correo


def validar_contrasena_inicial(contrasena, **datos_de_la_cuenta):
    """Una contraseña escrita a mano debe cumplir las reglas de seguridad de Django (largo, no común, no parecida al nombre…)."""
    if contrasena:
        password_validation.validate_password(contrasena, Usuario(**datos_de_la_cuenta))
    return contrasena


def campo_contrasena_inicial():
    return forms.CharField(
        required=False, max_length=64, label='Contraseña inicial', help_text=AYUDA_CONTRASENA, strip=False,
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'spellcheck': 'false', 'class': 'field__control--mono', 'placeholder': 'Se genera sola'}),
    )


# ---------------------------------------------------------------------------
# Alta y edición de una cuenta
# ---------------------------------------------------------------------------
class CuentaDeProfesorForm(EstiloCamposMixin, forms.Form):
    """«Dar acceso al sistema» desde la ficha del profesor: crea su cuenta o vincula una que ya existe.

    Va anidada en el formulario del profesor con el prefijo «acceso». Crear una cuenta pide el permiso de crear usuarios
    y vincular una existente, el de editarlos; el rol solo puede ser uno que quien captura también podría dar.
    """

    MODOS = [('nueva', 'Crear una cuenta nueva'), ('existente', 'Vincular una cuenta que ya existe')]

    dar_acceso = forms.BooleanField(required=False, label='Dar acceso al sistema')
    modo = forms.ChoiceField(choices=MODOS, required=False, initial='nueva', label='Cuenta', widget=forms.RadioSelect)
    username = forms.CharField(required=False, max_length=30, label='Usuario', help_text=AYUDA_USUARIO, widget=forms.TextInput(attrs={
        'autocomplete': 'off', 'autocapitalize': 'none', 'spellcheck': 'false', 'maxlength': 30, 'data-usuario': '',
    }))
    email = forms.EmailField(required=False, label='Correo de la cuenta', widget=forms.EmailInput(attrs={
        'autocomplete': 'off', 'placeholder': 'El del profesor',
    }), help_text='Opcional. Si lo dejas vacío se usa el correo de su ficha.')
    rol = forms.ModelChoiceField(queryset=Rol.objects.none(), required=False, label='Rol', empty_label='Elige un rol',
                                 help_text='Define qué puede ver y hacer en el sistema.')
    cuenta = forms.ModelChoiceField(queryset=Usuario.objects.none(), required=False, label='Cuenta', empty_label='Elige la cuenta',
                                    help_text='Cuentas activas que todavía no son de ningún profesor.')

    def __init__(self, *args, actor, profesor=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .docentes import cuentas_sin_profesor, rol_docente_predeterminado

        self.fields['contrasena'] = campo_contrasena_inicial()
        self.vinculada = profesor.usuario if profesor is not None and profesor.usuario_id else None
        self.puede_crear = actor.has_perm('auth.add_user')
        self.puede_vincular = actor.has_perm('auth.change_user')
        de_baja = profesor is not None and profesor.estatus != 'ACTIVO'
        self.disponible = self.vinculada is None and not de_baja and (self.puede_crear or self.puede_vincular)
        self.fields['modo'].choices = [(clave, texto) for clave, texto in self.MODOS
                                       if (clave == 'nueva' and self.puede_crear) or (clave == 'existente' and self.puede_vincular)]

        asignables = roles_asignables(actor) if self.puede_crear else []
        self.fields['rol'].queryset = Rol.objects.filter(pk__in=[rol.pk for rol in asignables]).select_related('grupo')
        self.fields['rol'].label_from_instance = lambda rol: rol.nombre
        predeterminado = rol_docente_predeterminado(asignables)
        if predeterminado:
            self.fields['rol'].initial = predeterminado.pk
        if self.disponible and self.puede_vincular:
            self.fields['cuenta'].queryset = Usuario.objects.filter(pk__in=[c.pk for c in cuentas_sin_profesor(actor)])
            self.fields['cuenta'].label_from_instance = lambda cuenta: f'{nombre_de(cuenta)} ({cuenta.username})'
        self.aplicar_estilo()

    @property
    def modo_elegido(self):
        return self.cleaned_data.get('modo') or (self.fields['modo'].choices[0][0] if self.fields['modo'].choices else '')

    @property
    def activo(self):
        return self.disponible and bool(self.cleaned_data.get('dar_acceso'))

    @property
    def mostrar(self):
        """Si la sección se dibuja abierta (antes de validar: con lo que se envió o se pidió abrir)."""
        return self.disponible and bool(self['dar_acceso'].value())

    @property
    def modo_actual(self):
        return self['modo'].value() or (self.fields['modo'].choices[0][0] if self.fields['modo'].choices else '')

    def clean(self):
        datos = super().clean()
        if not datos.get('dar_acceso') or self.vinculada is not None:
            return datos
        if not self.disponible:
            raise ValidationError('No tienes permiso para crear ni vincular cuentas de acceso.')
        if self.modo_elegido == 'existente':
            if not datos.get('cuenta'):
                self.add_error('cuenta', 'Elige la cuenta que será de este profesor.')
            return datos
        try:
            datos['username'] = validar_nombre_de_usuario(datos.get('username'))
        except ValidationError as error:
            self.add_error('username', error)
        try:
            datos['email'] = validar_correo_de_cuenta(datos.get('email'))
        except ValidationError as error:
            self.add_error('email', error)
        if not datos.get('rol'):
            self.add_error('rol', 'Elige el rol de la cuenta.')
        if datos.get('contrasena') and 'username' not in self.errors:
            try:
                validar_contrasena_inicial(datos['contrasena'], username=datos.get('username', ''), email=datos.get('email', ''))
            except ValidationError as error:
                self.add_error('contrasena', error)
        return datos

    def guardar(self, profesor):
        """Crea o vincula la cuenta. Devuelve (cuenta, contraseña en claro o None, ¿es nueva?) o (None, None, False)."""
        from .docentes import crear_cuenta, vincular

        if not self.activo or self.vinculada is not None:
            return None, None, False
        if self.modo_elegido == 'existente':
            return vincular(profesor, self.cleaned_data['cuenta']).usuario, None, False
        correo = self.cleaned_data.get('email') or ''
        if not correo and profesor.correo_electronico and not Usuario.objects.filter(email__iexact=profesor.correo_electronico).exists():
            correo = profesor.correo_electronico
        cuenta, contrasena = crear_cuenta(
            profesor, username=self.cleaned_data['username'], email=correo, rol=self.cleaned_data['rol'],
            contrasena=self.cleaned_data.get('contrasena', ''),
        )
        self.contrasena_escrita = bool(self.cleaned_data.get('contrasena'))
        return cuenta, contrasena, True


class DocenteDeCuentaForm(EstiloCamposMixin, forms.Form):
    """La parte «Es docente» del alta (o edición) de un usuario: su ficha de profesor, nueva o ya registrada.

    Va anidada en `UsuarioForm` con el prefijo «docente». El nombre del profesor nuevo es el de la cuenta, y su teléfono y
    correo, los de la cuenta; aquí solo se piden los apellidos por separado y lo propio del docente.
    """

    MODOS = [('nuevo', 'Registrar su ficha de profesor'), ('existente', 'Vincular con un profesor ya registrado')]

    es_docente = forms.BooleanField(required=False, label='Es docente')
    modo = forms.ChoiceField(choices=MODOS, required=False, initial='nuevo', label='Ficha de profesor', widget=forms.RadioSelect)
    profesor = forms.ModelChoiceField(
        queryset=None, required=False, label='Profesor', empty_label='Elige al profesor',
        help_text='Solo aparecen profesores activos que aún no tienen cuenta.',
    )
    apellido_paterno = forms.CharField(required=False, max_length=60, label='Apellido paterno', widget=forms.TextInput(attrs={'autocomplete': 'off'}))
    apellido_materno = forms.CharField(required=False, max_length=60, label='Apellido materno', widget=forms.TextInput(attrs={'autocomplete': 'off'}))
    especialidad = forms.CharField(required=False, max_length=150, label='Especialidad', widget=forms.TextInput(attrs={
        'autocomplete': 'off', 'placeholder': 'Matemáticas, inglés, educación física…',
    }))
    horas_maximas = forms.IntegerField(required=False, min_value=1, max_value=60, label='Horas máximas por semana', widget=forms.NumberInput(attrs={
        'min': 1, 'max': 60, 'inputmode': 'numeric', 'placeholder': 'Sin tope',
    }))
    materias = forms.ModelMultipleChoiceField(
        queryset=None, required=False, label='Materias que puede impartir', widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        help_text='Opcional. Aparecerá primero al asignar estas materias.',
    )

    def __init__(self, *args, actor, cuenta=None, **kwargs):
        super().__init__(*args, **kwargs)
        from Alumnos.models import Materia
        from .docentes import profesor_de, profesores_sin_cuenta

        self.actor = actor
        self.vinculado = profesor_de(cuenta)   # ya tiene ficha: aquí no hay nada que capturar
        self.forzado = False                   # el rol elegido es de docentes (lo fija UsuarioForm antes de validar)
        self.puede_crear = actor.has_perm('Alumnos.add_profesor')
        self.puede_vincular = actor.has_perm('Alumnos.change_profesor')
        self.disponible = self.vinculado is None and (self.puede_crear or self.puede_vincular)
        self.fields['modo'].choices = [(clave, texto) for clave, texto in self.MODOS
                                       if (clave == 'nuevo' and self.puede_crear) or (clave == 'existente' and self.puede_vincular)]
        self.fields['profesor'].queryset = profesores_sin_cuenta()
        self.fields['materias'].queryset = Materia.objects.filter(activa=True).order_by('nombre')
        self.profesor_creado = None
        self.aplicar_estilo()

    @property
    def activo(self):
        """¿Hay que crear o vincular una ficha? (marcó «Es docente» o eligió un rol de docentes)."""
        return self.vinculado is None and (self.forzado or bool(self.cleaned_data.get('es_docente')))

    @property
    def mostrar(self):
        """Si la sección se dibuja abierta (antes de validar: con lo que se envió)."""
        return self.vinculado is None and (self.forzado or bool(self['es_docente'].value()))

    @property
    def modo_actual(self):
        return self['modo'].value() or (self.fields['modo'].choices[0][0] if self.fields['modo'].choices else '')

    @property
    def modo_elegido(self):
        modo = self.cleaned_data.get('modo') or (self.fields['modo'].choices[0][0] if self.fields['modo'].choices else '')
        return modo

    def clean_apellido_paterno(self):
        return compactar_espacios(self.cleaned_data.get('apellido_paterno'))

    def clean_apellido_materno(self):
        return compactar_espacios(self.cleaned_data.get('apellido_materno'))

    def clean_especialidad(self):
        return compactar_espacios(self.cleaned_data.get('especialidad'))

    def clean(self):
        datos = super().clean()
        if not self.activo:
            return datos
        if not self.disponible:
            raise ValidationError('Para una cuenta de docente hay que registrar o vincular su ficha de profesor, y no tienes permiso para hacerlo.')
        modo = self.modo_elegido
        if modo == 'existente':
            if not datos.get('profesor'):
                self.add_error('profesor', 'Elige al profesor que tendrá esta cuenta.')
        elif not datos.get('apellido_paterno'):
            self.add_error('apellido_paterno', 'Escribe el apellido paterno.')
        return datos

    def guardar(self, cuenta, datos_de_la_cuenta):
        """Crea o vincula la ficha del profesor de `cuenta`. Devuelve el profesor (o None si no aplica)."""
        from Alumnos.docentes import habilitar
        from Alumnos.models import Profesor
        from .docentes import vincular

        if not self.activo:
            return None
        if self.modo_elegido == 'existente':
            return vincular(self.cleaned_data['profesor'], cuenta)
        correo = datos_de_la_cuenta.get('email') or None
        if correo and Profesor.objects.filter(correo_electronico__iexact=correo).exists():
            correo = None   # ya es de otro profesor: el formulario lo advierte antes, aquí solo se evita el choque
        profesor = Profesor.objects.create(
            nombre=datos_de_la_cuenta['first_name'],
            apellido_paterno=self.cleaned_data['apellido_paterno'],
            apellido_materno=self.cleaned_data.get('apellido_materno', ''),
            telefono=datos_de_la_cuenta.get('telefono', ''),
            correo_electronico=correo,
            especialidad=self.cleaned_data.get('especialidad', ''),
            horas_maximas=self.cleaned_data.get('horas_maximas'),
        )
        if self.cleaned_data.get('materias'):
            habilitar(profesor, self.cleaned_data['materias'])
        self.profesor_creado = profesor
        return vincular(profesor, cuenta)


class UsuarioForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición de un usuario. Al crear se puede escribir una contraseña inicial o dejar que se genere una temporal
    (se muestra una sola vez); después solo se restablece desde su perfil. Desactivar y reactivar son acciones aparte.

    Si la cuenta es de un docente (casilla «Es docente» o un rol para docentes), lleva anidado `self.docente` para
    registrar su ficha de profesor o vincularla con una existente: una sola cuenta para un solo profesor.
    """

    rol = forms.ModelChoiceField(queryset=Rol.objects.none(), label='Rol', empty_label='Elige un rol',
                                 help_text='Define qué puede ver y hacer. Sus permisos se administran en «Roles».')
    telefono = forms.CharField(required=False, label='Teléfono', widget=forms.TextInput(attrs={
        'inputmode': 'tel', 'autocomplete': 'off', 'placeholder': 'Opcional', 'data-phone': '',
    }))
    cargo = forms.CharField(required=False, max_length=80, label='Cargo o puesto', widget=forms.TextInput(attrs={
        'autocomplete': 'off', 'placeholder': 'Directora, secretaria, prefecto…',
    }))

    class Meta:
        model = Usuario
        fields = ['first_name', 'last_name', 'username', 'email']
        labels = {'first_name': 'Nombre', 'last_name': 'Apellidos', 'username': 'Usuario', 'email': 'Correo electrónico'}
        widgets = {
            'first_name': forms.TextInput(attrs={'autocomplete': 'off', 'autofocus': True}),
            'last_name': forms.TextInput(attrs={'autocomplete': 'off'}),
            'username': forms.TextInput(attrs={
                'autocomplete': 'off', 'autocapitalize': 'none', 'spellcheck': 'false', 'maxlength': 30, 'data-usuario': '',
            }),
            'email': forms.EmailInput(attrs={'autocomplete': 'off', 'placeholder': 'Opcional'}),
        }
        help_texts = {
            'username': AYUDA_USUARIO,
            'email': 'Opcional. Sirve para contactar a la persona.',
        }

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        from .docentes import profesor_de

        self.actor = actor
        self.contrasena_en_claro = None
        self.contrasena_escrita = False
        # Se exigen al validar: con la ficha de un profesor ya registrado, el nombre y los apellidos salen de ella
        self.fields['first_name'].required = False
        self.fields['last_name'].required = False
        self.fields['email'].required = False
        if not self.instance.pk:
            self.fields['contrasena'] = campo_contrasena_inicial()

        actual = rol_de(self.instance) if self.instance.pk else None
        elegibles = {rol.pk for rol in roles_asignables(actor)}
        if actual:
            elegibles.add(actual.pk)   # el rol que ya tiene siempre aparece, aunque ya no se pueda asignar
        self.fields['rol'].queryset = Rol.objects.filter(pk__in=elegibles).select_related('grupo')
        self.fields['rol'].label_from_instance = lambda rol: rol.nombre
        self.roles_docentes = [rol.pk for rol in self.fields['rol'].queryset if rol.es_docente]
        self.fields['rol'].widget.attrs['data-roles-docentes'] = ','.join(str(pk) for pk in self.roles_docentes)

        if self.instance.pk:
            perfil = PerfilUsuario.de(self.instance)
            self.initial.setdefault('rol', actual.pk if actual else None)
            self.initial.setdefault('telefono', perfil.telefono)
            self.initial.setdefault('cargo', perfil.cargo)

        # Nadie se cambia a sí mismo el rol, y al único administrador no se le puede quitar el acceso
        motivo = ''
        if self.instance.pk == actor.pk:
            motivo = 'No puedes cambiar tu propio rol; pídeselo a otra persona con ese permiso.'
        elif self.instance.pk and es_ultimo_administrador(self.instance):
            motivo = 'Es el único administrador activo: su rol no se puede cambiar.'
        if motivo:
            self.fields['rol'].disabled = True
            self.fields['rol'].required = False
            self.fields['rol'].help_text = motivo

        # La cuenta de un profesor toma el nombre de su ficha: se edita allá
        self.profesor = profesor_de(self.instance)
        if self.profesor is not None:
            for nombre in ('first_name', 'last_name'):
                self.fields[nombre].disabled = True
                self.fields[nombre].required = False
            self.fields['last_name'].help_text = 'Es la cuenta de un profesor: su nombre se cambia en su ficha de profesor.'

        self.docente = DocenteDeCuentaForm(self.data or None, prefix='docente', actor=actor, cuenta=self.instance)
        # Dar un rol para docentes (al crear la cuenta o al cambiarle el rol) exige su ficha de profesor. Una cuenta que ya
        # tenía ese rol sin ficha no se bloquea al editarla: se le avisa y puede vincularse aquí mismo.
        rol_enviado = str(self.data.get(self.add_prefix('rol'), '')) if self.is_bound else ''
        self.rol_docente_sin_ficha = bool(actual and actual.es_docente and self.profesor is None)
        self.docente.forzado = (
            rol_enviado.isdigit() and int(rol_enviado) in self.roles_docentes and self.profesor is None
            and not (actual and actual.pk == int(rol_enviado))
        )
        self.aplicar_estilo()

    @property
    def rol_docente_predeterminado(self):
        return self.roles_docentes[0] if self.roles_docentes else ''

    # --- validación conjunta (cuenta + ficha de profesor) -----------------------------------
    def is_valid(self):
        propio = super().is_valid()
        anidado = self.docente.is_valid()
        if propio and anidado:
            self._validar_con_la_ficha()
        return not self.errors and not self.docente.errors

    def _validar_con_la_ficha(self):
        from Alumnos.models import Profesor

        con_ficha = self.docente.activo
        nueva = con_ficha and self.docente.modo_elegido == 'nuevo'
        existente = con_ficha and not nueva
        if self.profesor is None and not existente:
            if not self.cleaned_data.get('first_name'):
                self.add_error('first_name', 'Este campo es obligatorio.')
            if not self.cleaned_data.get('last_name') and not nueva:
                self.add_error('last_name', 'Este campo es obligatorio.')
        if nueva:
            if not self.cleaned_data.get('telefono'):
                self.add_error('telefono', 'Escribe su teléfono: es obligatorio en la ficha del profesor.')
            correo = self.cleaned_data.get('email')
            if correo and Profesor.objects.filter(correo_electronico__iexact=correo).exists():
                self.add_error('email', 'Ese correo ya es de un profesor registrado: vincúlalo en lugar de registrar uno nuevo.')
        if 'contrasena' in self.fields and self.cleaned_data.get('contrasena'):
            try:
                validar_contrasena_inicial(
                    self.cleaned_data['contrasena'], username=self.cleaned_data.get('username', ''),
                    first_name=self.cleaned_data.get('first_name', ''), email=self.cleaned_data.get('email', ''),
                )
            except ValidationError as error:
                self.add_error('contrasena', error)

    # --- limpieza por campo ----------------------------------------------------------
    def clean_first_name(self):
        return compactar_espacios(self.cleaned_data.get('first_name'))

    def clean_last_name(self):
        return compactar_espacios(self.cleaned_data.get('last_name'))

    def clean_username(self):
        return validar_nombre_de_usuario(self.cleaned_data.get('username'), self.instance)

    def clean_email(self):
        return validar_correo_de_cuenta(self.cleaned_data.get('email'), self.instance)

    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono')
        return validar_telefono(telefono) if telefono else ''

    def clean_cargo(self):
        return compactar_espacios(self.cleaned_data.get('cargo'))

    def clean_rol(self):
        rol = self.cleaned_data.get('rol')
        if self.fields['rol'].disabled:
            return None
        return rol

    @transaction.atomic
    def save(self, commit=True):
        usuario = super().save(commit=False)
        nuevo = usuario.pk is None
        con_ficha_nueva = self.docente.activo and self.docente.modo_elegido == 'nuevo'
        if con_ficha_nueva:
            # El nombre de la cuenta es el de la ficha que se va a crear
            usuario.last_name = f"{self.docente.cleaned_data['apellido_paterno']} {self.docente.cleaned_data.get('apellido_materno', '')}".strip()
        if nuevo:
            escrita = self.cleaned_data.get('contrasena', '')
            self.contrasena_escrita = bool(escrita)
            self.contrasena_en_claro = escrita or contrasena_temporal()
            usuario.set_password(self.contrasena_en_claro)
            usuario.is_active = True
        usuario.save()

        perfil = PerfilUsuario.de(usuario)
        perfil.telefono = self.cleaned_data.get('telefono', '')
        perfil.cargo = self.cleaned_data.get('cargo', '') or ('Docente' if self.docente.activo else '')
        if nuevo:
            perfil.debe_cambiar_contrasena = True
        perfil.save()

        rol = self.cleaned_data.get('rol')
        self.rol_anterior = None if nuevo else rol_de(usuario)
        self.rol_cambio = bool(rol) and (nuevo or rol != self.rol_anterior)
        if self.rol_cambio:
            asignar_rol(usuario, rol)

        self.profesor_vinculado = self.docente.guardar(usuario, {**self.cleaned_data, 'first_name': usuario.first_name})
        return usuario


# ---------------------------------------------------------------------------
# Listado: filtros
# ---------------------------------------------------------------------------
class FiltroUsuariosForm(EstiloCamposMixin, forms.Form):
    ORDENES = {
        'nombre': ('first_name', 'last_name', 'username'),
        '-nombre': ('-first_name', '-last_name', '-username'),
        'reciente': ('-date_joined', 'username'),
        'acceso': ('-last_login', 'username'),
    }
    ORDEN_CHOICES = [
        ('nombre', 'Nombre (A-Z)'),
        ('-nombre', 'Nombre (Z-A)'),
        ('reciente', 'Cuenta más reciente'),
        ('acceso', 'Último acceso'),
    ]
    ESTADO_CHOICES = [('', 'Activos'), ('INACTIVO', 'Desactivados')]

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre, usuario, correo o cargo…', 'autocomplete': 'off',
    }))
    rol = forms.ChoiceField(required=False, label='Rol')
    estado = forms.ChoiceField(required=False, choices=ESTADO_CHOICES, label='Estado')
    orden = forms.ChoiceField(required=False, choices=ORDEN_CHOICES, label='Ordenar por')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rol'].choices = [
            ('', 'Todos los roles'),
            *[(str(rol.pk), rol.nombre) for rol in Rol.objects.select_related('grupo')],
            ('sin', 'Sin rol'),
        ]
        self.aplicar_estilo()

    @property
    def activos(self):
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}

    def filtrar(self, queryset, con_estado=True):
        datos = self.activos

        for palabra in datos.get('q', '').split():
            queryset = queryset.filter(
                Q(username__icontains=palabra) | Q(first_name__icontains=palabra) | Q(last_name__icontains=palabra)
                | Q(email__icontains=palabra) | Q(perfil__cargo__icontains=palabra)
            )

        if con_estado:
            queryset = queryset.filter(is_active=datos.get('estado') != 'INACTIVO')

        rol = datos.get('rol')
        if rol == 'sin':
            # Sin rol: ningún grupo con rol y que tampoco sea superusuario (estos cuentan como administradores)
            queryset = queryset.exclude(groups__rol__isnull=False).exclude(is_superuser=True)
        elif rol:
            # Todo superusuario cuenta como «Administrador», aunque no esté en el grupo de ese rol
            es_administrador = Rol.objects.filter(pk=rol, acceso_total=True).exists()
            queryset = queryset.filter(Q(groups__rol__pk=rol) | Q(is_superuser=True) if es_administrador else Q(groups__rol__pk=rol))

        return queryset.distinct().order_by(*self.ORDENES[datos.get('orden', 'nombre')])


# ---------------------------------------------------------------------------
# Mi cuenta
# ---------------------------------------------------------------------------
class MiCuentaForm(EstiloCamposMixin, forms.ModelForm):
    """Lo que cada persona puede cambiar de su propia cuenta. El usuario, el rol y el cargo los define quien administra."""

    telefono = forms.CharField(required=False, label='Teléfono', widget=forms.TextInput(attrs={
        'inputmode': 'tel', 'autocomplete': 'tel', 'placeholder': 'Opcional', 'data-phone': '',
    }))

    class Meta:
        model = Usuario
        fields = ['first_name', 'last_name', 'email']
        labels = {'first_name': 'Nombre', 'last_name': 'Apellidos', 'email': 'Correo electrónico'}
        widgets = {
            'first_name': forms.TextInput(attrs={'autocomplete': 'given-name'}),
            'last_name': forms.TextInput(attrs={'autocomplete': 'family-name'}),
            'email': forms.EmailInput(attrs={'autocomplete': 'email', 'placeholder': 'Opcional'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.initial.setdefault('telefono', PerfilUsuario.de(self.instance).telefono)
        from .docentes import profesor_de
        if profesor_de(self.instance) is not None:
            # La cuenta de un profesor toma el nombre de su ficha: lo corrige quien administra a los profesores
            for nombre in ('first_name', 'last_name'):
                self.fields[nombre].disabled = True
            self.fields['last_name'].help_text = 'Tu nombre sale de tu ficha de profesor; si hay un error, pide que lo corrijan ahí.'
        self.aplicar_estilo()

    def clean_first_name(self):
        return compactar_espacios(self.cleaned_data.get('first_name'))

    def clean_last_name(self):
        return compactar_espacios(self.cleaned_data.get('last_name'))

    def clean_email(self):
        correo = (self.cleaned_data.get('email') or '').strip().lower()
        if correo and Usuario.objects.filter(email__iexact=correo).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya hay una cuenta con ese correo electrónico.')
        return correo

    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono')
        return validar_telefono(telefono) if telefono else ''

    @transaction.atomic
    def save(self, commit=True):
        usuario = super().save()
        perfil = PerfilUsuario.de(usuario)
        perfil.telefono = self.cleaned_data.get('telefono', '')
        perfil.save(update_fields=['telefono', 'modificado'])
        return usuario


class CambioContrasenaForm(EstiloCamposMixin, PasswordChangeForm):
    """Cambio de la propia contraseña, con las reglas de seguridad de Django (largo, no común, no solo números...)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = 'Contraseña actual'
        self.fields['new_password1'].label = 'Contraseña nueva'
        self.fields['new_password2'].label = 'Repite la contraseña nueva'
        self.fields['old_password'].widget.attrs.update({'autocomplete': 'current-password', 'autofocus': True})
        for nombre in ('new_password1', 'new_password2'):
            self.fields[nombre].widget.attrs['autocomplete'] = 'new-password'
        self.aplicar_estilo()
