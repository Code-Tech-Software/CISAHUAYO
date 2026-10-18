"""Las notificaciones de los retiros, en la campana del sistema y de los portales (la misma de mensajes y comunicados).

- Al personal que atiende retiros (cualquiera de sus permisos) **y** cuyo alcance incluye a alguno de los estudiantes
  (Retiros/alcance.py): un aviso nuevo, las cancelaciones del tutor y las del personal. Quien hizo el cambio no se
  notifica a sí mismo.
- Al tutor que avisó: la salida confirmada de cada hijo, las cancelaciones del colegio y las correcciones.

Se guardan en la base de datos (contador y lista de la campana) y, al confirmarse la transacción, se avisan en tiempo
real por el canal de la mensajería (Retiros/tiempo_real.py). No hay correo, SMS ni WhatsApp: el sistema no los tiene.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from .alcance import DEL_PERSONAL, alcance_de, permite
from .models import Notificacion


def cuentas_del_personal():
    """Las cuentas activas con algún permiso de retiros (por su rol, por permiso suelto o por ser superusuario)."""
    codigos = [permiso.split('.')[1] for permiso in DEL_PERSONAL]
    return get_user_model().objects.filter(
        Q(is_superuser=True)
        | Q(groups__permissions__codename__in=codigos, groups__permissions__content_type__app_label='Retiros')
        | Q(user_permissions__codename__in=codigos, user_permissions__content_type__app_label='Retiros'),
        is_active=True,
    ).distinct()


def destinatarios_del_personal(retiros, excluir=None):
    destinatarios = []
    for usuario in cuentas_del_personal():
        if excluir is not None and usuario.pk == excluir.pk:
            continue
        alcance = alcance_de(usuario)
        if any(permite(alcance, retiro) for retiro in retiros):
            destinatarios.append(usuario)
    return destinatarios


def _guardar(notificaciones):
    creadas = Notificacion.objects.bulk_create(notificaciones)
    ids = [n.pk for n in creadas if n.pk]

    def avisar():
        from . import tiempo_real
        tiempo_real.avisar(ids)

    transaction.on_commit(avisar)
    return creadas


def al_personal(aviso, retiros, titulo, texto, excluir=None):
    return _guardar([Notificacion(usuario=usuario, aviso=aviso, titulo=titulo[:160], texto=texto[:300])
                     for usuario in destinatarios_del_personal(retiros, excluir=excluir)])


def al_tutor(aviso, titulo, texto):
    return _guardar([Notificacion(tutor_id=aviso.tutor_id, aviso=aviso, titulo=titulo[:160], texto=texto[:300])])


def pendientes_de(usuario=None, tutor=None):
    """Las notificaciones sin leer de una cuenta del personal o de un tutor."""
    if usuario is not None:
        return Notificacion.objects.filter(usuario=usuario, leida=False)
    return Notificacion.objects.filter(tutor=tutor, leida=False)


def marcar_leidas(aviso, usuario=None, tutor=None):
    """Al abrir un aviso, sus notificaciones quedan leídas. Devuelve cuántas cambiaron."""
    return pendientes_de(usuario=usuario, tutor=tutor).filter(aviso=aviso).update(leida=True)
