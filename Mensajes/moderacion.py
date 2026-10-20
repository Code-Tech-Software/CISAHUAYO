"""Moderación de la mensajería (pedido del 2026-10-20): el administrador busca en todas las conversaciones del colegio
(por persona, por texto o por fechas) y retira los mensajes inapropiados.

Retirar es borrar por completo: el mensaje, su formato, sus imágenes y sus archivos. No queda copia, marca, aviso de que
existió ni registro de quién lo retiró; la conversación sigue como si nunca se hubiera enviado (su vista previa pasa al
mensaje anterior). Las pantallas abiertas de las dos personas lo quitan al momento (Mensajes/tiempo_real.avisar_retiro).
El permiso (`Mensajes.moderar`) es exclusivo del rol Administrador (Usuarios/catalogo.py).
"""
import logging
import re

from django.db import transaction
from django.db.models import Count, Q
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from .models import Conversacion, Mensaje, Miembro, Participante

MODERAR = 'Mensajes.moderar'
CON_CUENTA = ('autor__usuario', 'autor__alumno', 'autor__tutor')

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
    consulta = Mensaje.objects.select_related(*CON_CUENTA).annotate(con_imagenes=Count('imagenes'))
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


def resaltar(texto, buscado='', largo=220):
    """El texto en una línea, recortado alrededor de la primera coincidencia, con las palabras buscadas en <mark> (todo
    lo demás, escapado)."""
    texto = ' '.join((texto or '').split())
    palabras = [re.escape(p) for p in (buscado or '').split()]
    patron = re.compile('|'.join(palabras), re.IGNORECASE) if palabras else None
    inicio = 0
    if patron and (primera := patron.search(texto)) and primera.start() > largo // 3:
        inicio = primera.start() - largo // 4
    fragmento = texto[inicio:inicio + largo]
    partes = []
    if patron:
        ultimo = 0
        for coincidencia in patron.finditer(fragmento):
            partes.append(conditional_escape(fragmento[ultimo:coincidencia.start()]))
            partes.append(f'<mark>{conditional_escape(coincidencia.group())}</mark>')
            ultimo = coincidencia.end()
        partes.append(conditional_escape(fragmento[ultimo:]))
    else:
        partes.append(conditional_escape(fragmento))
    return mark_safe(('…' if inicio else '') + ''.join(partes) + ('…' if inicio + largo < len(texto) else ''))


# ---------------------------------------------------------------------------
# Una conversación completa
# ---------------------------------------------------------------------------
def miembros_de(conversacion):
    return list(Participante.objects.filter(membresias__conversacion=conversacion).select_related('usuario', 'alumno', 'tutor').order_by('pk'))


def ventana(conversacion, alrededor=None, cantidad=40):
    """(mensajes en orden, hay_anteriores, hay_posteriores): los últimos `cantidad` o, con `alrededor` (el id de un
    mensaje), los que están antes y después de él."""
    base = conversacion.mensajes.select_related(*CON_CUENTA)
    if alrededor:
        mitad = cantidad // 2
        previos = list(base.filter(pk__lt=alrededor).order_by('-pk')[:mitad + 1])
        siguientes = list(base.filter(pk__gte=alrededor).order_by('pk')[:mitad + 1])
        return list(reversed(previos[:mitad])) + siguientes[:mitad], len(previos) > mitad, len(siguientes) > mitad
    mensajes = list(base.order_by('-pk')[:cantidad + 1])
    return list(reversed(mensajes[:cantidad])), len(mensajes) > cantidad, False


# ---------------------------------------------------------------------------
# Retirar
# ---------------------------------------------------------------------------
def retirar(mensaje):
    """Borra el mensaje por completo: su texto, su formato, sus imágenes (y sus archivos). La conversación queda con el
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
