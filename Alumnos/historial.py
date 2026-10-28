"""El historial de cambios de un estudiante (pedido del 2026-10-28): quién registró, corrigió sus datos, cambió su estatus,
su grupo o su acceso al portal, y cuándo. Se guarda en la bitácora del sistema (LogEntry, como los usuarios y los roles:
Usuarios/seguridad.py) y se ve en su expediente. Las contraseñas nunca se escriben: solo que se cambió.
"""
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType

ALTA, CAMBIO, BAJA = ADDITION, CHANGE, DELETION
# Campos del formulario que no se nombran por su etiqueta (o que no se anotan)
SIN_ANOTAR = {'contrasena', 'contrasena_confirmacion'}


def anotar(usuario, alumno, mensaje, accion=CAMBIO):
    from Usuarios.seguridad import registrar
    if usuario is None or not getattr(usuario, 'pk', None):
        return None
    return registrar(usuario, alumno, accion, mensaje[:2000])


def anotar_varios(usuario, mensajes):
    """Muchas anotaciones de una vez (la promoción de ciclo): `mensajes` es {id del estudiante: texto}."""
    from .models import Alumno
    if usuario is None or not getattr(usuario, 'pk', None) or not mensajes:
        return []
    tipo = ContentType.objects.get_for_model(Alumno)
    nombres = dict((pk, str(a)) for pk, a in ((a.pk, a) for a in Alumno.objects.filter(pk__in=list(mensajes))))
    return LogEntry.objects.bulk_create([
        LogEntry(user_id=usuario.pk, content_type=tipo, object_id=str(pk), object_repr=nombres.get(pk, '')[:200], action_flag=CAMBIO,
                 change_message=texto[:2000])
        for pk, texto in mensajes.items()
    ])


def _lista(nombres):
    nombres = list(nombres)
    if len(nombres) < 2:
        return ''.join(nombres)
    return f'{", ".join(nombres[:-1])} y {nombres[-1]}'


def campos_cambiados(form, excluir=()):
    """«nombre, domicilio y fotografía» de los campos que cambiaron en el formulario (sin las contraseñas ni `excluir`)."""
    etiquetas = []
    for campo in form.changed_data:
        if campo in SIN_ANOTAR or campo in excluir or campo not in form.fields:
            continue
        etiquetas.append(str(form.fields[campo].label or campo).lower())
    return _lista(etiquetas)


def de(alumno, limite=60):
    """Las anotaciones del estudiante, de la más reciente a la más antigua, con quién las hizo."""
    tipo = ContentType.objects.get_for_model(alumno)
    return list(LogEntry.objects.filter(content_type=tipo, object_id=str(alumno.pk)).select_related('user').order_by('-action_time', '-pk')[:limite])


def nombre_de_accion(entrada):
    return {ALTA: 'Alta', CAMBIO: 'Cambio', BAJA: 'Baja'}.get(entrada.action_flag, 'Cambio')
