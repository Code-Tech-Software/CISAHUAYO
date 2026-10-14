"""Permisos del módulo de conducta y quién puede hacer qué con cada registro.

Lo usan la administración (permisos del modelo: Conducta.*_registroconducta) y prefectura (Prefectura.*), con la misma
pantalla y los mismos datos. Una cuenta de prefectura además solo ve a los estudiantes de su alcance
(Prefectura/alcance.py) y:
- corrige o anula sus propios registros mientras estén abiertos, siempre con motivo; los de otros y los casos cerrados
  solo con «Corregir de otros» (Prefectura.corregir_otros);
- da seguimiento (citas, acuerdos, compromisos, cierre) con Prefectura.dar_seguimiento;
- solo aplica las medidas habilitadas para prefectura, y toda suspensión o medida que requiera aprobación queda
  pendiente hasta que alguien con Conducta.aprobar_suspension la resuelva (nunca quien la pidió);
- no administra los catálogos.
Los permisos se comprueban en el servidor en cada vista; los botones solo reflejan lo mismo.
"""

VER = 'Conducta.view_registroconducta'
REGISTRAR = 'Conducta.add_registroconducta'
EDITAR = 'Conducta.change_registroconducta'
ANULAR = 'Conducta.delete_registroconducta'
APROBAR = 'Conducta.aprobar_suspension'

PREF_CONSULTAR = 'Prefectura.consultar'
PREF_REGISTRAR = 'Prefectura.registrar'
PREF_CORREGIR = 'Prefectura.corregir'
PREF_CORREGIR_OTROS = 'Prefectura.corregir_otros'
PREF_JUSTIFICAR = 'Prefectura.justificar'
PREF_SOLICITAR = 'Prefectura.solicitar_suspension'
PREF_SEGUIMIENTO = 'Prefectura.dar_seguimiento'
PREF_EXPORTAR = 'Prefectura.exportar'

# Para los decoradores: basta uno de cada par (el de la administración o el de prefectura)
CONSULTAR = (VER, PREF_CONSULTAR)
ALTA = (REGISTRAR, PREF_REGISTRAR)
CAMBIO = (EDITAR, PREF_CORREGIR, PREF_CORREGIR_OTROS, PREF_SEGUIMIENTO)

CONFIGURACION = (
    'Conducta.view_categoriaconducta',
    'Conducta.view_motivoconducta',
    'Conducta.view_medidadisciplinaria',
    'Conducta.view_motivosuspension',
    'Conducta.view_reglareincidencia',
)


def puede_configurar(usuario):
    """Si ve alguno de los catálogos de conducta (la pestaña «Conducta» de Ajustes)."""
    return any(usuario.has_perm(permiso) for permiso in CONFIGURACION)


# ---------------------------------------------------------------------------
# Qué puede hacer la persona
# ---------------------------------------------------------------------------
def es_administracion(usuario):
    """Usa el módulo con los permisos de la administración (sin los límites de prefectura)."""
    return usuario.has_perm(VER)


def puede_ver(usuario):
    return usuario.has_perm(VER) or usuario.has_perm(PREF_CONSULTAR)


def puede_registrar(usuario):
    return usuario.has_perm(REGISTRAR) or usuario.has_perm(PREF_REGISTRAR)


def niveles_que_aprueba(usuario):
    """Los niveles cuyas suspensiones y medidas autoriza: la dirección de cada nivel (Usuarios › ficha › «Niveles que
    dirige»). None = todos (el administrador); vacío = ninguno."""
    if not usuario.has_perm(APROBAR):
        return set()
    if usuario.is_superuser:
        return None
    guardado = getattr(usuario, '_niveles_direccion', None)
    if guardado is None:
        from Usuarios.models import PerfilUsuario
        guardado = set(PerfilUsuario.objects.filter(usuario=usuario).values_list('niveles_direccion', flat=True).first() or [])
        usuario._niveles_direccion = guardado
    return guardado


def puede_aprobar(usuario, nivel=None):
    """Si autoriza las de ese nivel (sin nivel: si autoriza las de alguno)."""
    niveles = niveles_que_aprueba(usuario)
    if niveles is None:
        return True
    return (nivel in niveles) if nivel else bool(niveles)


def solo_medidas_de_prefectura(usuario):
    """Si solo puede aplicar las medidas habilitadas para prefectura (no tiene los permisos de la administración)."""
    return not (usuario.has_perm(REGISTRAR) or usuario.has_perm(EDITAR))


def _propio_y_abierto(usuario, registro):
    return registro.registrado_por_id == usuario.pk and registro.estado != registro.CERRADO


def de_ciclo_cerrado(registro):
    """Un registro de un ciclo que ya se cerró es de solo lectura para todos (pedido del 2026-10-14)."""
    return registro.ciclo.estado == 'CERRADO'


def puede_corregir(usuario, registro):
    """Editar el registro (siempre con motivo del cambio)."""
    if registro.anulado or de_ciclo_cerrado(registro):
        return False
    if usuario.has_perm(EDITAR) or usuario.has_perm(PREF_CORREGIR_OTROS):
        return True
    return usuario.has_perm(PREF_CORREGIR) and _propio_y_abierto(usuario, registro)


def puede_anular(usuario, registro):
    if registro.anulado or de_ciclo_cerrado(registro):
        return False
    if usuario.has_perm(ANULAR) or usuario.has_perm(PREF_CORREGIR_OTROS):
        return True
    return usuario.has_perm(PREF_CORREGIR) and _propio_y_abierto(usuario, registro)


def puede_dar_seguimiento(usuario, registro):
    """Seguimiento, citas, contactos, compromisos, evidencias y avisos de reincidencia del registro."""
    if registro.anulado or de_ciclo_cerrado(registro):
        return False
    if usuario.has_perm(EDITAR):
        return True
    if not usuario.has_perm(PREF_SEGUIMIENTO):
        return False
    return registro.estado != registro.CERRADO or usuario.has_perm(PREF_CORREGIR_OTROS)


def puede_pedir_suspension(usuario):
    """Si al registrar o corregir puede pedir (o registrar, si aprueba) una suspensión."""
    return puede_aprobar(usuario) or usuario.has_perm(REGISTRAR) or usuario.has_perm(EDITAR) or usuario.has_perm(PREF_SOLICITAR)


def puede_exportar(usuario):
    return usuario.has_perm(VER) or usuario.has_perm(PREF_EXPORTAR)
