"""Qué retiros ve y atiende cada cuenta del personal: el alcance por nivel educativo.

- Consultar exige `Retiros.consultar`; confirmar salidas, `Retiros.confirmar`; cancelar avisos y corregir salidas,
  `Retiros.corregir`. Configurar los motivos, `Retiros.configurar`.
- El administrador (`Retiros.gestionar`, exclusivo del rol de acceso total) ve los de todo el colegio.
- Cualquier otra cuenta, solo los de los estudiantes de sus niveles: los «Niveles para retiros» de su ficha de usuario y,
  si es una cuenta de prefectura, también su alcance de prefectura (niveles completos, grupos o todo el colegio).
  Sin ninguno no ve retiros (la pantalla lo explica).

El nivel y el grupo de cada estudiante son los de su inscripción cuando se avisó (RetiroEstudiante.inscripcion). Toda
consulta y acción del personal pasa por aquí: lo que queda fuera responde 404.
"""
from django.db import DatabaseError

from Prefectura.alcance import NINGUNO, NOMBRE_DE_NIVEL, TOTAL, Alcance

CONSULTAR = 'Retiros.consultar'
CONFIRMAR = 'Retiros.confirmar'
CORREGIR = 'Retiros.corregir'
GESTIONAR = 'Retiros.gestionar'
CONFIGURAR = 'Retiros.configurar'
DEL_PERSONAL = (CONSULTAR, CONFIRMAR, CORREGIR, GESTIONAR)

SIN_NIVELES = ('No tienes niveles educativos asignados para retiros anticipados. Pide al administrador que te los asigne en '
               'tu ficha de usuario («Niveles para retiros»).')


def usa_retiros(usuario):
    """Si la cuenta atiende retiros (cualquiera de los permisos del personal)."""
    return bool(usuario and usuario.is_authenticated and usuario.is_active and any(usuario.has_perm(p) for p in DEL_PERSONAL))


def niveles_de_cuenta(usuario):
    """Los «Niveles para retiros» de su ficha (vacío si no tiene o aún no se migra Usuarios)."""
    from Usuarios.models import PerfilUsuario
    try:
        niveles = PerfilUsuario.objects.filter(usuario=usuario).values_list('niveles_retiros', flat=True).first() or []
    except DatabaseError:
        niveles = []
    return frozenset(n for n in niveles if n in NOMBRE_DE_NIVEL)


def alcance_de(usuario):
    """El alcance de retiros de la cuenta (se calcula una vez por petición: queda en el objeto del usuario)."""
    if not usa_retiros(usuario):
        return NINGUNO
    guardado = getattr(usuario, '_alcance_retiros', None)
    if guardado is not None:
        return guardado
    if usuario.has_perm(GESTIONAR):
        alcance = TOTAL
    else:
        niveles, grupos, todo = set(niveles_de_cuenta(usuario)), set(), False
        from Prefectura.alcance import alcance_de as alcance_de_prefectura
        from Prefectura.alcance import es_cuenta_de_prefectura
        if es_cuenta_de_prefectura(usuario):
            prefectura = alcance_de_prefectura(usuario)
            todo = prefectura.todo
            niveles |= set(prefectura.niveles)
            grupos |= set(prefectura.grupos)
        alcance = Alcance(restringido=True, todo=todo, niveles=frozenset(niveles), grupos=frozenset(grupos))
    usuario._alcance_retiros = alcance
    return alcance


def condicion(alcance):
    """La condición sobre `RetiroEstudiante` (por el nivel y el grupo de la inscripción con que se avisó)."""
    return alcance.condicion(nivel='inscripcion__grado__nivel', grupo='inscripcion__grupo')


def permite(alcance, retiro):
    """Si el estudiante de ese retiro está en el alcance."""
    return alcance.total or alcance.permite_grupo(retiro.inscripcion.grupo)
