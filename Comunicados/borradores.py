"""Los borradores de comunicados (2026-10-31): lo que alguien lleva escrito y todavía no envía.

Se guardan en su propia tabla (`BorradorComunicado`): ninguna consulta de los comunicados ni de sus destinatarios los ve,
así que un borrador no puede llegarle a nadie por error. Solo su autor los consulta. Se guarda lo que haya en el formulario,
sin validarlo (puede estar a medias): todo se revisa al enviarlo, con Comunicados/reglas.enviar. Los archivos se conservan
en `AdjuntoBorrador` y las imágenes del texto quedan ligadas al borrador para que no se borren al día siguiente.
"""
import re

from django.core.exceptions import ValidationError
from django.utils import timezone

from Conducta.forms import validar_archivo

from .models import AdjuntoBorrador, BorradorComunicado, Comunicado, ImagenComunicado
from .reglas import EnvioRechazado

# Los campos del formulario que se guardan tal como vienen
CAMPOS = ('descripcion', 'html', 'urgente', 'categoria', 'fijado', 'respuesta', 'pregunta', 'responder_fecha', 'responder_hora',
          'publicar_fecha', 'publicar_hora', 'expira_fecha', 'expira_hora', 'evento_fecha', 'evento_hora_inicio', 'evento_hora_fin',
          'evento_lugar', 'destinatarios', 'evento_agenda')
MAXIMO_POR_CAMPO = Comunicado.MAXIMO_HTML * 3


def de(usuario, pk):
    """El borrador de esa persona, o None."""
    if not str(pk or '').isdigit():
        return None
    return BorradorComunicado.objects.filter(pk=pk, autor=usuario).first()


def _ligar_imagenes(borrador, html):
    ids = {int(pk) for pk in re.findall(r'data-imagen="(\d+)"', html or '')}
    propias = ImagenComunicado.objects.filter(autor=borrador.autor, comunicado__isnull=True)
    propias.filter(borrador=borrador).exclude(pk__in=ids).update(borrador=None)
    propias.filter(pk__in=ids).update(borrador=borrador)


def guardar(usuario, datos, archivos=(), borrador=None, base=None):
    """Crea o actualiza el borrador con los campos de `datos` (el POST del formulario) y los `archivos` nuevos. Con
    `guardar_adjuntos`, solo se quedan los que traiga marcados (`adjuntos_borrador`). EnvioRechazado si no se puede."""
    if borrador is None and BorradorComunicado.objects.filter(autor=usuario).count() >= BorradorComunicado.MAXIMO_POR_PERSONA:
        raise EnvioRechazado(f'Ya tienes {BorradorComunicado.MAXIMO_POR_PERSONA} borradores. Envía o descarta alguno para guardar otro.')
    valores = {campo: datos.get(campo, '') for campo in CAMPOS}
    if any(len(str(valor)) > MAXIMO_POR_CAMPO for valor in valores.values()):
        raise EnvioRechazado('El borrador es demasiado largo.')
    valores['opciones'] = [texto[:120] for texto in datos.getlist('opciones') if texto.strip()][:Comunicado.MAXIMO_OPCIONES]

    guardados = borrador.adjuntos.count() if borrador is not None else 0
    conservar = None
    if borrador is not None and 'guardar_adjuntos' in datos:
        conservar = [int(pk) for pk in datos.getlist('adjuntos_borrador') if pk.isdigit()]
        guardados = borrador.adjuntos.filter(pk__in=conservar).count()
    if guardados + len(archivos) > Comunicado.MAXIMO_ADJUNTOS:
        raise EnvioRechazado(f'Adjunta como máximo {Comunicado.MAXIMO_ADJUNTOS} archivos.')
    validados = []
    for archivo in archivos:
        try:
            validados.append((archivo, validar_archivo(archivo)))
        except ValidationError as error:
            raise EnvioRechazado(' '.join(error.messages)) from None

    if borrador is None:
        borrador = BorradorComunicado(autor=usuario, base=base)
    borrador.titulo = ' '.join((datos.get('titulo') or '').split())[:Comunicado.MAXIMO_TITULO]
    borrador.datos = valores
    borrador.actualizado = timezone.now()
    borrador.save()
    _ligar_imagenes(borrador, valores['html'])
    if conservar is not None:
        for adjunto in borrador.adjuntos.exclude(pk__in=conservar):
            adjunto.archivo.delete(save=False)
            adjunto.delete()
    for archivo, tipo in validados:
        nombre = (archivo.name or 'archivo').replace('\\', '/').rsplit('/', 1)[-1][:200]
        AdjuntoBorrador.objects.create(borrador=borrador, archivo=archivo, nombre_original=nombre, tipo=tipo, tamano=archivo.size)
    return borrador


def eliminar(borrador):
    """Lo descarta con sus archivos. Sus imágenes quedan sueltas y se borran con las demás que nunca se enviaron."""
    for adjunto in borrador.adjuntos.all():
        adjunto.archivo.delete(save=False)
    borrador.delete()
