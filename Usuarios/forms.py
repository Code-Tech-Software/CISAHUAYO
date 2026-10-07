import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from Alumnos.forms import EstiloCamposMixin
from Alumnos.utils import compactar_espacios, validar_telefono

from .models import PerfilUsuario, Rol
from .seguridad import asignar_rol, contrasena_temporal, es_ultimo_administrador, rol_de, roles_asignables

Usuario = get_user_model()

NOMBRE_DE_USUARIO_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{2,29}$')


# ---------------------------------------------------------------------------
# Alta y edición de una cuenta
# ---------------------------------------------------------------------------
class UsuarioForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición de un usuario. La contraseña no se escribe aquí: al crear se genera una temporal (que se muestra
    una sola vez) y después solo se restablece desde su perfil. Desactivar y reactivar son acciones aparte."""

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
            'username': 'Con él inicia sesión. De 3 a 30 caracteres: minúsculas, números, punto, guion y guion bajo.',
            'email': 'Opcional. Sirve para contactar a la persona.',
        }

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.contrasena_en_claro = None
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = False

        actual = rol_de(self.instance) if self.instance.pk else None
        elegibles = {rol.pk for rol in roles_asignables(actor)}
        if actual:
            elegibles.add(actual.pk)   # el rol que ya tiene siempre aparece, aunque ya no se pueda asignar
        self.fields['rol'].queryset = Rol.objects.filter(pk__in=elegibles).select_related('grupo')
        self.fields['rol'].label_from_instance = lambda rol: rol.nombre

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
        self.aplicar_estilo()

    # --- limpieza por campo ----------------------------------------------------------
    def clean_first_name(self):
        return compactar_espacios(self.cleaned_data.get('first_name'))

    def clean_last_name(self):
        return compactar_espacios(self.cleaned_data.get('last_name'))

    def clean_username(self):
        valor = (self.cleaned_data.get('username') or '').strip()
        if self.instance.pk and valor == self.instance.username:
            return valor   # una cuenta que ya existía conserva su usuario aunque no cumpla la regla actual
        valor = valor.lower()
        if not NOMBRE_DE_USUARIO_RE.match(valor):
            raise ValidationError('Usa de 3 a 30 caracteres: minúsculas, números, punto, guion o guion bajo, empezando con letra o número.')
        repetido = Usuario.objects.filter(username__iexact=valor).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise ValidationError('Ya existe una cuenta con ese usuario.')
        return valor

    def clean_email(self):
        correo = (self.cleaned_data.get('email') or '').strip().lower()
        if correo and Usuario.objects.filter(email__iexact=correo).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya hay una cuenta con ese correo electrónico.')
        return correo

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
        if nuevo:
            self.contrasena_en_claro = contrasena_temporal()
            usuario.set_password(self.contrasena_en_claro)
            usuario.is_active = True
        usuario.save()

        perfil = PerfilUsuario.de(usuario)
        perfil.telefono = self.cleaned_data.get('telefono', '')
        perfil.cargo = self.cleaned_data.get('cargo', '')
        if nuevo:
            perfil.debe_cambiar_contrasena = True
        perfil.save()

        rol = self.cleaned_data.get('rol')
        self.rol_anterior = None if nuevo else rol_de(usuario)
        self.rol_cambio = bool(rol) and (nuevo or rol != self.rol_anterior)
        if self.rol_cambio:
            asignar_rol(usuario, rol)
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
