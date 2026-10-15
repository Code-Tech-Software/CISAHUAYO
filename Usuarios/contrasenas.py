"""Contraseña consultable de las cuentas del sistema (pedido del 2026-10-15, como en estudiantes y tutores).

La contraseña que asigna o restablece quien administra (al crear la cuenta, al darle acceso a un profesor o con
«Restablecer contraseña») se guarda también legible en `PerfilUsuario.contrasena_visible`, y solo un administrador
(superusuario) la ve en el perfil de la cuenta. Nunca se guarda una contraseña elegida por la propia persona: si la
contraseña cambia por cualquier otro camino («Mi cuenta», el cambio obligatorio al entrar, el admin de Django,
`manage.py changepassword`…), la copia legible se borra sola (`olvidar_si_cambia`, señal pre_save de la cuenta), así que
lo que se consulta siempre es la contraseña vigente o nada.
"""
from django.contrib.auth.hashers import check_password


def consultable(usuario):
    """La contraseña vigente legible de la cuenta, o '' si no se puede consultar."""
    perfil = getattr(usuario, 'perfil', None)
    if perfil is None or not usuario.has_usable_password():
        return ''
    return perfil.contrasena_visible


def olvidar_si_cambia(sender, instance, raw=False, update_fields=None, **kwargs):
    """Antes de guardar una cuenta: si su contraseña cambió a otra distinta de la consultable, borra la copia legible.

    Se conserva cuando la nueva es la misma (Django vuelve a cifrarla al entrar si cambió el algoritmo, o quien
    administra la asigna de nuevo)."""
    from .models import PerfilUsuario

    if raw or instance.pk is None or (update_fields is not None and 'password' not in update_fields):
        return
    perfil = PerfilUsuario.objects.filter(usuario_id=instance.pk).exclude(contrasena_visible='').first()
    if perfil is None:
        return
    nueva = getattr(instance, '_password', None)   # la contraseña en claro si se acaba de usar set_password()
    if nueva is not None:
        sigue = nueva == perfil.contrasena_visible
    else:
        anterior = sender.objects.filter(pk=instance.pk).values_list('password', flat=True).first()
        if anterior == instance.password:
            return
        sigue = check_password(perfil.contrasena_visible, instance.password)   # solo cambió el cifrado
    if not sigue:
        PerfilUsuario.objects.filter(pk=perfil.pk).update(contrasena_visible='')
