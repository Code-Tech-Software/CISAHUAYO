from django import forms
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction

from Alumnos.forms import EstiloCamposMixin
from Alumnos.utils import compactar_espacios
from Usuarios.catalogo import TODOS, con_requisitos, etiqueta_de
from Usuarios.models import Rol
from Usuarios.seguridad import codigos, objetos_de_permisos, permisos_de_rol, permisos_efectivos

MAXIMO_NOMBRE = 80


class RolForm(EstiloCamposMixin, forms.Form):
    """Alta y edición de un rol: nombre, descripción, color y la matriz de permisos.

    Los permisos llegan como una lista `permisos` de casillas («Alumnos.view_alumno»...). Se les suma lo que cada uno
    necesita (editar exige ver), y quien edita solo puede cambiar los permisos que él mismo tiene: los demás se
    conservan tal como estaban (la casilla aparece bloqueada).
    """

    nombre = forms.CharField(max_length=MAXIMO_NOMBRE, label='Nombre del rol', widget=forms.TextInput(attrs={
        'autocomplete': 'off', 'autofocus': True, 'placeholder': 'Coordinación académica, Prefectura…',
    }))
    descripcion = forms.CharField(required=False, max_length=200, label='Descripción', widget=forms.TextInput(attrs={
        'autocomplete': 'off', 'placeholder': 'Para qué sirve este rol',
    }), help_text='Opcional. Ayuda a elegir el rol correcto al crear una cuenta.')
    tono = forms.TypedChoiceField(choices=Rol.TONOS, coerce=int, initial=1, label='Color', widget=forms.RadioSelect)
    es_docente = forms.BooleanField(required=False, label='Rol para docentes')

    def __init__(self, *args, actor, rol=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.rol = rol
        self.permisos_del_actor = permisos_efectivos(actor)
        self.permisos_actuales = permisos_de_rol(rol) if rol else set()
        self.permisos_finales = set(self.permisos_actuales)
        self.otorgados, self.retirados = [], []
        if rol and not self.is_bound:
            self.initial = {'nombre': rol.nombre, 'descripcion': rol.descripcion, 'tono': rol.tono, 'es_docente': rol.es_docente}
        self.aplicar_estilo()

    # --- permisos marcados (para volver a dibujar la matriz) ---------------------------
    @property
    def marcados(self):
        """Lo que la matriz debe mostrar marcado: lo enviado si hubo envío, y si no el estado del rol."""
        if self.is_bound:
            enviados = set(self.data.getlist('permisos')) & TODOS
            return con_requisitos(enviados) | (self.permisos_actuales - self.permisos_del_actor)
        return set(self.permisos_actuales)

    # --- validación --------------------------------------------------------------------
    def clean_nombre(self):
        nombre = compactar_espacios(self.cleaned_data.get('nombre'))
        if not nombre:
            raise ValidationError('Escribe un nombre para el rol.')
        repetido = Group.objects.filter(name__iexact=nombre)
        if self.rol:
            repetido = repetido.exclude(pk=self.rol.grupo_id)
        if repetido.exists():
            raise ValidationError('Ya existe un rol con ese nombre.')
        return nombre

    def clean_descripcion(self):
        return compactar_espacios(self.cleaned_data.get('descripcion'))

    def clean(self):
        datos = super().clean()
        pedidos = set(self.data.getlist('permisos'))
        desconocidos = pedidos - TODOS
        if desconocidos:
            raise ValidationError('Se enviaron permisos que no existen. Recarga la página e inténtalo de nuevo.')
        pedidos = con_requisitos(pedidos)

        # Solo se puede conceder lo que uno mismo tiene
        sin_derecho = (pedidos - self.permisos_del_actor) - self.permisos_actuales
        if sin_derecho:
            nombres = ', '.join(sorted(etiqueta_de(p) for p in sin_derecho)[:4])
            raise ValidationError(f'No puedes conceder permisos que tú no tienes: {nombres}.')
        self.permisos_finales = (pedidos & self.permisos_del_actor) | (self.permisos_actuales - self.permisos_del_actor)
        return datos

    # --- guardado ----------------------------------------------------------------------
    @transaction.atomic
    def save(self):
        datos = self.cleaned_data
        if self.rol is None:
            grupo = Group.objects.create(name=datos['nombre'])
            rol = Rol.objects.create(grupo=grupo, descripcion=datos['descripcion'], tono=datos['tono'], es_docente=datos.get('es_docente', False))
            fuera_del_catalogo = set()
        else:
            rol = self.rol
            grupo = rol.grupo
            grupo.name = datos['nombre']
            grupo.save(update_fields=['name'])
            rol.descripcion = datos['descripcion']
            rol.tono = datos['tono']
            rol.es_docente = datos.get('es_docente', False)
            rol.save(update_fields=['descripcion', 'tono', 'es_docente', 'modificado'])
            # Permisos que alguien puso desde el admin de Django y no son del catálogo: se respetan
            fuera_del_catalogo = codigos(grupo.permissions.select_related('content_type')) - TODOS

        grupo.permissions.set(objetos_de_permisos(self.permisos_finales | fuera_del_catalogo))
        self.otorgados = sorted(self.permisos_finales - self.permisos_actuales)
        self.retirados = sorted(self.permisos_actuales - self.permisos_finales)
        self.rol = rol
        return rol
