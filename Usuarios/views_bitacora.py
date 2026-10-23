"""Bitácora de cambios (pedido del 2026-10-23): la pantalla para que el administrador consulte quién hizo qué.

Lee el mismo historial donde el sistema ya anota los cambios (LogEntry: Usuarios/seguridad.registrar, las asignaciones,
los comunicados y el admin de Django). Solo consulta: nada aquí escribe ni borra entradas.
"""
from django import forms
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.shortcuts import render

from Alumnos.forms import EstiloCamposMixin
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_permisos

ACCIONES = {ADDITION: ('Alta', 'success'), CHANGE: ('Cambio', 'info'), DELETION: ('Baja', 'danger')}


def _nombre_de_seccion(tipo):
    return str(tipo.model_class()._meta.verbose_name_plural).capitalize() if tipo.model_class() else tipo.model


class FiltroBitacoraForm(EstiloCamposMixin, forms.Form):
    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Qué cambió o sobre quién…', 'autocomplete': 'off',
    }))
    quien = forms.ChoiceField(required=False, label='Quién')
    seccion = forms.ChoiceField(required=False, label='Sección')
    accion = forms.ChoiceField(required=False, label='Acción', choices=[
        ('', 'Todas las acciones'), *((str(clave), nombre) for clave, (nombre, _) in ACCIONES.items()),
    ])
    desde = forms.DateField(required=False, label='Desde', widget=forms.DateInput(attrs={'type': 'date'}))
    hasta = forms.DateField(required=False, label='Hasta', widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        autores = get_user_model().objects.filter(
            pk__in=LogEntry.objects.values('user_id').distinct()).order_by('first_name', 'last_name', 'username')
        self.fields['quien'].choices = [('', 'Todas las personas'), *(
            (str(u.pk), u.get_full_name().strip() or u.get_username()) for u in autores)]
        tipos = ContentType.objects.filter(pk__in=LogEntry.objects.values('content_type_id').distinct())
        self.fields['seccion'].choices = [('', 'Todas las secciones'), *sorted(
            ((str(t.pk), _nombre_de_seccion(t)) for t in tipos), key=lambda opcion: opcion[1])]
        self.aplicar_estilo()

    def filtrar(self, entradas):
        if not self.is_valid():
            return entradas
        datos = self.cleaned_data
        if datos['q']:
            entradas = entradas.filter(Q(change_message__icontains=datos['q']) | Q(object_repr__icontains=datos['q']))
        if datos['quien']:
            entradas = entradas.filter(user_id=datos['quien'])
        if datos['seccion']:
            entradas = entradas.filter(content_type_id=datos['seccion'])
        if datos['accion']:
            entradas = entradas.filter(action_flag=datos['accion'])
        if datos['desde']:
            entradas = entradas.filter(action_time__date__gte=datos['desde'])
        if datos['hasta']:
            entradas = entradas.filter(action_time__date__lte=datos['hasta'])
        return entradas

    @property
    def activos(self):
        return self.is_valid() and any(self.cleaned_data.values())


def _texto(entrada):
    """El mensaje tal cual lo anotó el sistema; las entradas del admin de Django guardan JSON y se leen con su método."""
    mensaje = entrada.get_change_message() if entrada.change_message.startswith('[') else entrada.change_message
    return mensaje or {ADDITION: 'Se dio de alta.', CHANGE: 'Se modificó.', DELETION: 'Se eliminó.'}.get(entrada.action_flag, '')


@requiere_permisos('admin.view_logentry')
def bitacora(request):
    filtro = FiltroBitacoraForm(request.GET or None)
    consulta = filtro.filtrar(LogEntry.objects.select_related('user', 'content_type').order_by('-action_time', '-pk'))
    pagina, rango_paginas, por_pagina = paginar(request, consulta)
    entradas = [{
        'cuando': entrada.action_time,
        'quien': (entrada.user.get_full_name().strip() or entrada.user.get_username()) if entrada.user_id else 'Sistema',
        'accion': ACCIONES.get(entrada.action_flag, ('Cambio', 'info')),
        'seccion': _nombre_de_seccion(entrada.content_type) if entrada.content_type_id else '—',
        'sobre': entrada.object_repr,
        'texto': _texto(entrada),
    } for entrada in pagina]
    return render(request, 'usuarios/bitacora.html', {
        'filtro': filtro,
        'filtros_activos': filtro.activos,
        'pagina': pagina,
        'entradas': entradas,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
    })
