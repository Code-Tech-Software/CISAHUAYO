"""Moderación de la mensajería (pedido del 2026-10-20): el administrador busca en todas las conversaciones del colegio
(por persona, por texto o por fechas) y retira los mensajes inapropiados.

Retirar es borrar por completo: el mensaje, su formato, sus imágenes y sus archivos. No queda copia, marca, aviso de que
existió ni registro de quién lo retiró; la conversación sigue como si nunca se hubiera enviado (su vista previa pasa al
mensaje anterior). Las pantallas abiertas de las dos personas lo quitan al momento (Mensajes/tiempo_real.avisar_retiro).
El permiso (`Mensajes.moderar`) es exclusivo del rol Administrador (Usuarios/catalogo.py).

Desde el 2026-10-27 quien recibe un mensaje puede reportarlo (Mensajes/reglas.reportar): los reportados esperan aquí a
que el administrador los retire o descarte el reporte. Y el administrador puede recorrer todas las conversaciones del
colegio (las de los docentes con estudiantes, con tutores o entre el personal), no solo buscar en ellas: es la decisión
del colegio para las conversaciones privadas entre docentes y estudiantes.
"""
import logging

from django.db import transaction
from django.db.models import Count, Exists, Max, OuterRef, Prefetch, Q

from .models import Conversacion, ImagenMensaje, Mensaje, Miembro, Participante, ReporteMensaje
from .reglas import CON_CUENTA
from .reglas import ventana as ventana_alrededor

MODERAR = 'Mensajes.moderar'

registro = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------
def personas_que_coinciden(texto):
    """Los participantes (de cualquier clase de cuenta) cuyo nombre, usuario o referencia contiene cada palabra."""
    consulta = Participante.objects.all()
    for palabra in (texto or '').split():
        consulta = consulta.filter(
            Q(usuario__first_name__icontains=palabra) | Q(usuario__last_name__icontains=palabra) | Q(usuario__username__icontains=palabra)
            | Q(alumno__nombre__icontains=palabra) | Q(alumno__apellido_paterno__icontains=palabra)
            | Q(alumno__apellido_materno__icontains=palabra) | Q(alumno__referencia__icontains=palabra)
            | Q(tutor__nombre__icontains=palabra) | Q(tutor__apellido_paterno__icontains=palabra)
            | Q(tutor__apellido_materno__icontains=palabra) | Q(tutor__usuario__icontains=palabra)
        )
    return consulta


def buscar(persona='', texto='', desde=None, hasta=None):
    """Los mensajes de todas las conversaciones que coinciden, del más reciente al más antiguo. `persona`: los de las
    conversaciones donde participa (los que escribió y los que recibió); `texto`: cada palabra en el mensaje."""
    consulta = Mensaje.objects.select_related(*CON_CUENTA).annotate(
        con_imagenes=Count('imagenes', filter=Q(imagenes__tipo__startswith='image/')),
        con_documentos=Count('imagenes', filter=Q(imagenes__tipo=ImagenMensaje.DOCUMENTO)),
    )
    if persona:
        consulta = consulta.filter(conversacion__in=Miembro.objects.filter(participante__in=personas_que_coinciden(persona)).values('conversacion'))
    for palabra in (texto or '').split():
        consulta = consulta.filter(texto__icontains=palabra)
    if desde:
        consulta = consulta.filter(creado__date__gte=desde)
    if hasta:
        consulta = consulta.filter(creado__date__lte=hasta)
    return consulta.order_by('-pk')


def con_destinatarios(mensajes):
    """Pone en cada mensaje `para`: la otra persona de su conversación."""
    mensajes = list(mensajes)
    miembros = {}
    for miembro in Miembro.objects.filter(conversacion__in={m.conversacion_id for m in mensajes}).select_related(
            'participante__usuario', 'participante__alumno', 'participante__tutor'):
        miembros.setdefault(miembro.conversacion_id, []).append(miembro.participante)
    for mensaje in mensajes:
        mensaje.para = next((p for p in miembros.get(mensaje.conversacion_id, []) if p.pk != mensaje.autor_id), None)
    return mensajes


# ---------------------------------------------------------------------------
# Mensajes reportados
# ---------------------------------------------------------------------------
def reportados_pendientes():
    """Cuántos mensajes reportados esperan revisión (la campana de quien modera)."""
    return Mensaje.objects.filter(Exists(ReporteMensaje.objects.filter(mensaje=OuterRef('pk')))).count()


def reportados():
    """Los mensajes reportados, del reporte más reciente al más antiguo, con sus reportes (`reportes_de`: quién y por
    qué) y la otra persona de la conversación (`para`, con `con_destinatarios`)."""
    return (Mensaje.objects.filter(Exists(ReporteMensaje.objects.filter(mensaje=OuterRef('pk'))))
            .select_related(*CON_CUENTA)
            .annotate(ultimo_reporte=Max('reportes__creado'))
            .prefetch_related(Prefetch('reportes', to_attr='reportes_de', queryset=ReporteMensaje.objects.select_related(
                'participante__usuario', 'participante__alumno', 'participante__tutor').order_by('creado')))
            .order_by('-ultimo_reporte', '-pk'))


def descartar_reportes(mensaje):
    """El mensaje no es inapropiado: se borran sus reportes y se queda en la conversación (sin dejar marca)."""
    return ReporteMensaje.objects.filter(mensaje=mensaje).delete()[0]


# ---------------------------------------------------------------------------
# Todas las conversaciones
# ---------------------------------------------------------------------------
# Con quién es la conversación (además del personal): para recorrer, por ejemplo, solo las de docentes con estudiantes
CON_ESTUDIANTE, CON_TUTOR, ENTRE_PERSONAL = 'ESTUDIANTE', 'TUTOR', 'PERSONAL'
TIPOS_DE_CONVERSACION = [
    (CON_ESTUDIANTE, 'Con estudiantes'),
    (CON_TUTOR, 'Con tutores'),
    (ENTRE_PERSONAL, 'Entre el personal'),
]


def conversaciones(persona='', tipo=''):
    """Las conversaciones del colegio que tienen mensajes, de la más reciente a la más antigua, con cuántos mensajes
    tienen. `persona`: donde participa alguien cuyo nombre, usuario o referencia coincide; `tipo`: CON_ESTUDIANTE,
    CON_TUTOR o ENTRE_PERSONAL."""
    consulta = Conversacion.objects.filter(ultimo_mensaje__isnull=False).select_related('ultimo_mensaje').annotate(
        total=Count('mensajes', distinct=True))
    if persona:
        consulta = consulta.filter(pk__in=Miembro.objects.filter(participante__in=personas_que_coinciden(persona)).values('conversacion'))
    con = {t: Miembro.objects.filter(conversacion=OuterRef('pk'), participante__tipo=t) for t in (Participante.ESTUDIANTE, Participante.TUTOR)}
    if tipo == CON_ESTUDIANTE:
        consulta = consulta.filter(Exists(con[Participante.ESTUDIANTE]))
    elif tipo == CON_TUTOR:
        consulta = consulta.filter(Exists(con[Participante.TUTOR]))
    elif tipo == ENTRE_PERSONAL:
        consulta = consulta.exclude(Exists(con[Participante.ESTUDIANTE])).exclude(Exists(con[Participante.TUTOR]))
    return consulta.order_by('-actualizada', '-pk')


def con_miembros(conversaciones):
    """Pone en cada conversación `miembros_de`: sus dos participantes (las familias y los estudiantes primero, como en la
    pantalla de la conversación)."""
    conversaciones = list(conversaciones)
    miembros = {}
    for miembro in Miembro.objects.filter(conversacion__in=conversaciones).select_related(
            'participante__usuario', 'participante__alumno', 'participante__tutor'):
        miembros.setdefault(miembro.conversacion_id, []).append(miembro.participante)
    for conversacion in conversaciones:
        conversacion.miembros_de = sorted(miembros.get(conversacion.pk, []), key=lambda p: (p.tipo == Participante.SISTEMA, p.pk))
    return conversaciones


# ---------------------------------------------------------------------------
# Una conversación completa
# ---------------------------------------------------------------------------
def miembros_de(conversacion):
    return list(Participante.objects.filter(membresias__conversacion=conversacion).select_related('usuario', 'alumno', 'tutor').order_by('pk'))


def ventana(conversacion, alrededor=None, cantidad=40):
    """(mensajes en orden, hay_anteriores, hay_posteriores): los últimos `cantidad` o, con `alrededor` (el id de un
    mensaje), los que están antes y después de él."""
    if alrededor:
        return ventana_alrededor(conversacion, alrededor, cantidad)
    mensajes = list(conversacion.mensajes.select_related(*CON_CUENTA).order_by('-pk')[:cantidad + 1])
    return list(reversed(mensajes[:cantidad])), len(mensajes) > cantidad, False


# ---------------------------------------------------------------------------
# Retirar
# ---------------------------------------------------------------------------
def retirar(mensaje):
    """Borra el mensaje por completo: su texto, su formato, sus imágenes y documentos (y sus archivos). La conversación queda con el
    mensaje anterior como el último (o vacía, y deja de aparecer en la bandeja). No se guarda nada de lo retirado."""
    conversacion_id, mensaje_id = mensaje.conversacion_id, mensaje.pk
    archivos = [(imagen.archivo.storage, imagen.archivo.name) for imagen in mensaje.imagenes.all() if imagen.archivo]
    with transaction.atomic():
        mensaje.delete()   # sus imágenes, en cascada; la conversación pierde su «último mensaje» si era este
        ultimo = Mensaje.objects.filter(conversacion=conversacion_id).order_by('-pk').first()
        conversacion = Conversacion.objects.get(pk=conversacion_id)
        conversacion.ultimo_mensaje = ultimo
        conversacion.actualizada = ultimo.creado if ultimo else conversacion.creada
        conversacion.save(update_fields=['ultimo_mensaje', 'actualizada'])

        def despues():
            for almacen, nombre in archivos:
                try:
                    almacen.delete(nombre)
                except Exception:   # el registro ya no existe: el archivo, sin nadie que lo entregue, queda inaccesible
                    registro.exception('No se pudo borrar el archivo de una imagen retirada')
            from . import tiempo_real
            tiempo_real.avisar_retiro(conversacion_id, mensaje_id)

        transaction.on_commit(despues)
