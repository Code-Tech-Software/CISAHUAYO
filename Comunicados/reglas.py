"""Las operaciones de los comunicados: enviar, corregir, leer, responder, listar, dar seguimiento, recordar y eliminar.

- Enviar: lo valida todo en el servidor (alcance de quien envía, destinatarios, fechas de publicación y de expiración,
  respuesta que se pide, evento) y lo guarda de una sola vez (comunicado, destinatarios, opciones, archivos e imágenes
  del texto). La `clave_envio` que trae el formulario hace que un doble clic o un reintento devuelvan el mismo
  comunicado en lugar de crear otro. El aviso sale en segundo plano (Comunicados/avisos.py); si se programó, al llegar
  su hora.
- Corregir (2026-10-27): el autor (o el administrador) cambia el texto, el título, la urgencia, la expiración, la
  categoría, si va fijado, el evento y los archivos; los destinatarios y la respuesta que se pide no cambian (las
  lecturas y las respuestas se conservan). Queda «Editado» para quien lo recibe y en el historial. Con respuestas ya
  dadas hay que decir qué fue (2026-10-31): una corrección menor las conserva; un cambio importante las pasa al historial
  (`RespuestaAnterior`) y pide responder otra vez, porque un «Sí» no vale para algo distinto. Mientras siga programado
  nadie lo ha visto: se pueden cambiar sus destinatarios y publicarlo ya hay que pedirlo expresamente.
- Abrir: la primera vez que el destinatario abre el detalle se guarda la fecha y hora; abrirlo otra vez no la cambia. Ver
  la fila, recibir el aviso o que el autor o el administrador consulten el seguimiento no cuenta. Abrir no es confirmar:
  solo dice que la pantalla se abrió. Confirmar es responder (`Comunicado.ENTERADO`).
- Responder (2026-10-27): «Enterado», Sí o No a una autorización, o una opción de una encuesta. Se puede cambiar
  mientras el comunicado siga activo y dentro de su plazo, si lo tiene (lo último que eligió es lo que cuenta).
- Autorizar (2026-11-01): es por estudiante. Un tutor con varios hijos responde por cada uno; cada estudiante queda
  autorizado, no autorizado o, si sus tutores se contradicen, en desacuerdo, que no cuenta como autorizado hasta que el
  colegio lo aclare. Basta el «Sí» de un tutor si el otro no responde.
- Por atender (2026-10-31): lo que falta abrir y lo abierto que todavía espera respuesta. Es lo que cuentan el menú y la
  campana: abrir una autorización sin responderla no la saca de la lista de pendientes.
- Sin acceso al portal (2026-10-31): quien no tiene cómo entrar no puede abrirlo. Se muestra aparte y no cuenta en los
  porcentajes ni en «Recordar».
- Publicar y caducar: un comunicado programado no se ve antes de su hora, y uno con fecha de expiración ya cumplida deja
  de verse y de abrirse para sus destinatarios (aun con un enlace directo); se compara con la hora del servidor en cada
  consulta. El autor y el administrador conservan el histórico con sus estadísticas.
- Gestionar: el administrador, todos; los demás, solo los suyos (pertenecer al mismo nivel no deja ver los de otros).
"""
from dataclasses import dataclass
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import escape
from django.utils.safestring import mark_safe

from Alumnos.academico import ciclo_actual
from Alumnos.models import ORDEN_NIVELES, Inscripcion
from Mensajes import enriquecido

from .alcance import ELIMINAR, ENVIAR, RECIBIR, SEGUIMIENTO, SIN_NIVELES, FueraDeAlcance, alcance_de, es_administrador
from .models import (
    Adjunto, AutorizacionEstudiante, Comunicado, Destinatario, ImagenComunicado, OpcionEncuesta, RespuestaAnterior, sin_acceso_al_portal,
)

PLURAL = {Destinatario.TUTOR: ('tutor', 'tutores'), Destinatario.ESTUDIANTE: ('estudiante', 'estudiantes'),
          Destinatario.PROFESOR: ('profesor', 'profesores'), Destinatario.PERSONAL: ('persona del personal', 'personas del personal')}
ORDEN_DE_TIPOS = (Destinatario.TUTOR, Destinatario.ESTUDIANTE, Destinatario.PROFESOR, Destinatario.PERSONAL)
PROGRAMAR_HASTA = timedelta(days=180)
ESPERA_ENTRE_RECORDATORIOS = timedelta(hours=1)
# Al corregir un comunicado que ya tiene respuestas
CAMBIO_MENOR, CAMBIO_IMPORTANTE = 'MENOR', 'IMPORTANTE'


class EnvioRechazado(Exception):
    def __init__(self, mensaje, campo=None):
        super().__init__(mensaje)
        self.mensaje, self.campo = mensaje, campo


def cantidad(numero, tipo):
    singular, plural = PLURAL[tipo]
    return f'{numero} {singular if numero == 1 else plural}'


def resumen_por_tipo(conteos, vacio='Sin destinatarios'):
    """«22 tutores · 15 estudiantes · 4 profesores» (solo los tipos que tienen alguien)."""
    partes = [cantidad(conteos.get(tipo, 0), tipo) for tipo in ORDEN_DE_TIPOS if conteos.get(tipo)]
    return ' · '.join(partes) or vacio


def porcentaje(leidos, total):
    """Porcentaje entero de lectura. Nunca dice 100 % si falta alguien ni 0 % si ya leyó alguno; con cero
    destinatarios, 0."""
    if not total:
        return 0
    valor = round(leidos * 100 / total)
    if leidos and valor == 0:
        return 1
    if leidos < total and valor == 100:
        return 99
    return valor


def nombre_de_usuario(usuario):
    from Usuarios.seguridad import nombre_de
    return nombre_de(usuario)


def rol_visible(usuario):
    """Cómo se presenta a quien envía: su rol («Docente», «Dirección», «Administrador»…)."""
    from Usuarios.docentes import profesor_de
    from Usuarios.seguridad import rol_de
    rol = rol_de(usuario)
    if rol is not None:
        return rol.nombre
    return 'Docente' if profesor_de(usuario) is not None else 'Personal del colegio'


# ---------------------------------------------------------------------------
# El contenido: texto con formato, enlaces y la respuesta que se pide
# ---------------------------------------------------------------------------
def preparar_contenido(usuario, descripcion, html='', comunicado=None):
    """(texto plano, html limpio, ids de imágenes) de lo que se escribió. Con `html` (el editor con formato), el texto
    sale de él y el HTML se limpia en el servidor: solo quedan las imágenes que esa persona subió y todavía no envió (y,
    al corregir, las que ya tenía el comunicado). Sin formato real se guarda solo el texto. EnvioRechazado si queda vacío
    o es demasiado largo."""
    imagenes = []
    if html and html.strip():
        if len(html) > Comunicado.MAXIMO_HTML * 3:
            raise EnvioRechazado('La descripción es demasiado larga.', 'descripcion')
        validas = set(ImagenComunicado.objects.filter(autor=usuario, comunicado__isnull=True).values_list('pk', flat=True))
        if comunicado is not None:
            validas |= set(comunicado.imagenes.values_list('pk', flat=True))
        limpio, imagenes = enriquecido.limpiar(html, imagenes_validas=validas)
        if enriquecido.tiene_contenido(limpio):
            texto = enriquecido.texto_plano(limpio)
            if enriquecido.es_texto_simple(limpio):
                limpio = ''
        else:
            limpio, texto, imagenes = '', '', []
        if len(limpio) > Comunicado.MAXIMO_HTML:
            raise EnvioRechazado('La descripción tiene demasiado contenido o formato. Divídela en varios comunicados.', 'descripcion')
    else:
        limpio, texto = '', (descripcion or '').strip()
    if not texto.strip():
        raise EnvioRechazado('Escribe la descripción del comunicado.', 'descripcion')
    if len(texto) > Comunicado.MAXIMO_DESCRIPCION:
        raise EnvioRechazado(f'La descripción puede tener hasta {Comunicado.MAXIMO_DESCRIPCION} caracteres.', 'descripcion')
    return texto, limpio, imagenes


enlazar = enriquecido.enlazar   # las direcciones del texto, como enlaces (Mensajes/enriquecido.py)


def contenido_visible(comunicado, url_de_imagen):
    """El contenido listo para mostrarse: el HTML (limpio otra vez, con las imágenes por la ruta de quien mira) o el texto
    en párrafos; con las direcciones como enlaces."""
    if comunicado.html:
        return mark_safe(enlazar(enriquecido.presentar(comunicado.html, url_de_imagen)))
    return mark_safe(enriquecido.texto_con_enlaces(comunicado.descripcion))


def html_para_editar(comunicado, url_de_imagen):
    """Lo que se pone en el editor para corregirlo o usarlo como base."""
    if comunicado.html:
        return enriquecido.presentar(comunicado.html, url_de_imagen)
    return ''.join(f'<p>{escape(renglon)}</p>' if renglon.strip() else '<p><br></p>' for renglon in comunicado.descripcion.split('\n'))


def validar_respuesta(respuesta, pregunta='', opciones=()):
    """(respuesta, pregunta, opciones) normalizadas. Una encuesta pide su pregunta y de 2 a 6 opciones distintas."""
    respuesta = respuesta or Comunicado.SIN_RESPUESTA
    if respuesta not in dict(Comunicado.RESPUESTAS):
        raise EnvioRechazado('Elige qué respuesta se pide.', 'respuesta')
    pregunta = ' '.join((pregunta or '').split())[:200]
    if respuesta != Comunicado.ENCUESTA:
        return respuesta, pregunta if respuesta == Comunicado.AUTORIZACION else '', []
    limpias, vistas = [], set()
    for opcion in opciones or ():
        texto = ' '.join((opcion or '').split())[:120]
        if texto and texto.lower() not in vistas:
            vistas.add(texto.lower())
            limpias.append(texto)
    if not pregunta:
        raise EnvioRechazado('Escribe la pregunta de la encuesta.', 'respuesta')
    if not 2 <= len(limpias) <= Comunicado.MAXIMO_OPCIONES:
        raise EnvioRechazado(f'La encuesta necesita de 2 a {Comunicado.MAXIMO_OPCIONES} opciones distintas.', 'respuesta')
    return respuesta, pregunta, limpias


def validar_evento(fecha=None, hora_inicio=None, hora_fin=None, lugar=''):
    """{evento_fecha, evento_hora_inicio, evento_hora_fin, evento_lugar}: sin fecha no hay evento."""
    lugar = ' '.join((lugar or '').split())[:150]
    if fecha is None:
        if hora_inicio or hora_fin or lugar:
            raise EnvioRechazado('Elige la fecha del evento (o borra su hora y su lugar).', 'evento')
        return {'evento_fecha': None, 'evento_hora_inicio': None, 'evento_hora_fin': None, 'evento_lugar': ''}
    if hora_fin and not hora_inicio:
        raise EnvioRechazado('Elige también la hora de inicio del evento.', 'evento')
    if hora_inicio and hora_fin and hora_fin <= hora_inicio:
        raise EnvioRechazado('La hora de fin del evento debe ser después de la de inicio.', 'evento')
    return {'evento_fecha': fecha, 'evento_hora_inicio': hora_inicio, 'evento_hora_fin': hora_fin, 'evento_lugar': lugar}


def _validar_categoria(categoria):
    categoria = categoria or ''
    if categoria and categoria not in dict(Comunicado.CATEGORIAS):
        raise EnvioRechazado('Elige una categoría de la lista.', 'categoria')
    return categoria


def _validar_publicacion(publicar_en, expira, ahora):
    """El momento de publicación (ahora, o el programado) revisando las dos fechas."""
    if publicar_en is not None:
        if publicar_en <= ahora + timedelta(minutes=1):
            raise EnvioRechazado('La fecha de publicación debe ser posterior a este momento.', 'publicar')
        if publicar_en > ahora + PROGRAMAR_HASTA:
            raise EnvioRechazado('Se puede programar hasta seis meses adelante.', 'publicar')
    publicado = publicar_en or ahora
    if expira is not None and expira <= publicado:
        raise EnvioRechazado('La fecha de expiración debe ser posterior al momento del envío.' if publicar_en is None
                             else 'La fecha de expiración debe ser posterior a la publicación.', 'expira')
    return publicado


def _validar_plazo(responder_hasta, respuesta, publicado, expira):
    if responder_hasta is None:
        return
    if not respuesta:
        raise EnvioRechazado('Solo se pone plazo si se pide una respuesta.', 'respuesta')
    if responder_hasta <= publicado:
        raise EnvioRechazado('El plazo para responder debe ser posterior a la publicación.', 'respuesta')
    if expira is not None and responder_hasta > expira:
        raise EnvioRechazado('El plazo para responder no puede ser después de la fecha de expiración.', 'respuesta')


def _crear_destinatarios(comunicado, alcance, elegidos):
    detalles = alcance.detalles(elegidos)
    grupos = alcance.grupos_de(elegidos)
    campo = {Destinatario.ESTUDIANTE: 'alumno_id', Destinatario.TUTOR: 'tutor_id', Destinatario.PROFESOR: 'profesor_id',
             Destinatario.PERSONAL: 'usuario_id'}
    Destinatario.objects.bulk_create([
        Destinatario(comunicado=comunicado, tipo=tipo, detalle=detalles[tipo].get(pk, '')[:250],
                     grupo_id=grupos.get(tipo, {}).get(pk), **{campo[tipo]: pk})
        for tipo in ORDEN_DE_TIPOS for pk in sorted(elegidos.get(tipo, ()))
    ])
    if comunicado.respuesta == Comunicado.AUTORIZACION:
        tutores = sorted(elegidos.get(Destinatario.TUTOR, ()))
        hijos = alcance.hijos_de(tutores)
        copias = dict(comunicado.destinatarios.filter(tipo=Destinatario.TUTOR).values_list('tutor_id', 'pk'))
        AutorizacionEstudiante.objects.bulk_create([
            AutorizacionEstudiante(destinatario_id=copias[tutor], alumno=alumno)
            for tutor in tutores for alumno in hijos.get(tutor, [])
        ])


def _copiar_archivo(archivo, nombre):
    archivo.open('rb')
    try:
        return ContentFile(archivo.read(), name=nombre)
    finally:
        archivo.close()


# ---------------------------------------------------------------------------
# Enviar
# ---------------------------------------------------------------------------
def enviar(autor, *, titulo, descripcion, urgente, expira, clave_envio, seleccion, archivos=(), ahora=None, html='',
           categoria='', fijado=False, publicar_en=None, respuesta='', pregunta='', opciones=(), evento=None, copiar_adjuntos=(),
           responder_hasta=None):
    """Guarda el comunicado y lo publica (ahora o a la hora programada en `publicar_en`). Devuelve (comunicado, nuevo):
    `nuevo` es False si esa clave de envío ya se había usado (doble clic o reintento). `archivos`: [(archivo subido, tipo
    real)] ya validados; `copiar_adjuntos`: archivos de otro comunicado (al usarlo como base) que se copian a este;
    `evento`: {fecha, hora_inicio, hora_fin, lugar}. EnvioRechazado si no procede."""
    ahora = ahora or timezone.now()
    previo = Comunicado.objects.filter(clave_envio=clave_envio).first()
    if previo is not None:
        if previo.autor_id != autor.pk:
            raise EnvioRechazado('El formulario caducó. Vuelve a abrirlo para enviar el comunicado.')
        return previo, False

    alcance = alcance_de(autor)
    if not alcance.puede_enviar:
        raise EnvioRechazado(SIN_NIVELES)
    publicado = _validar_publicacion(publicar_en, expira, ahora)
    texto, limpio, imagenes = preparar_contenido(autor, descripcion, html)
    respuesta, pregunta, opciones = validar_respuesta(respuesta, pregunta, opciones)
    _validar_plazo(responder_hasta, respuesta, publicado, expira)
    datos_del_evento = validar_evento(**(evento or {}))
    categoria = _validar_categoria(categoria)
    try:
        elegidos = alcance.validar(seleccion)
    except FueraDeAlcance:
        raise EnvioRechazado('Algunas de las personas elegidas están fuera de los niveles a los que puedes enviar. Vuelve a '
                             'elegir los destinatarios.', 'destinatarios') from None
    if not any(elegidos.values()):
        raise EnvioRechazado('Elige al menos un destinatario.', 'destinatarios')
    copiar_adjuntos = list(copiar_adjuntos or ())
    if len(archivos) + len(copiar_adjuntos) > Comunicado.MAXIMO_ADJUNTOS:
        raise EnvioRechazado(f'Adjunta como máximo {Comunicado.MAXIMO_ADJUNTOS} archivos.', 'archivos')

    inmediato = publicar_en is None
    try:
        with transaction.atomic():
            comunicado = Comunicado.objects.create(
                titulo=titulo, descripcion=texto, html=limpio, urgente=urgente, expira=expira, autor=autor,
                rol_autor=rol_visible(autor)[:80], creado=ahora, publicado_en=publicado,
                clave_envio=clave_envio, categoria=categoria, fijado=fijado, respuesta=respuesta, pregunta=pregunta,
                responder_hasta=responder_hasta, **datos_del_evento,
            )
            _crear_destinatarios(comunicado, alcance, elegidos)
            OpcionEncuesta.objects.bulk_create([OpcionEncuesta(comunicado=comunicado, texto=t, orden=i) for i, t in enumerate(opciones)])
            if imagenes:
                ImagenComunicado.objects.filter(pk__in=imagenes, autor=autor, comunicado__isnull=True).update(comunicado=comunicado)
            orden = 0
            for adjunto in copiar_adjuntos:
                Adjunto.objects.create(comunicado=comunicado, archivo=_copiar_archivo(adjunto.archivo, adjunto.nombre_original),
                                       nombre_original=adjunto.nombre_original, tipo=adjunto.tipo, tamano=adjunto.tamano, orden=orden)
                orden += 1
            for archivo, tipo in archivos:
                Adjunto.objects.create(comunicado=comunicado, archivo=archivo, nombre_original=_nombre_de_archivo(archivo.name),
                                       tipo=tipo, tamano=archivo.size, orden=orden)
                orden += 1
            from Usuarios.seguridad import ACCION_ALTA, registrar
            total = sum(len(ids) for ids in elegidos.values())
            programado = '' if inmediato else f' Programado para el {timezone.localtime(publicado):%d/%m/%Y %H:%M}.'
            registrar(autor, comunicado, ACCION_ALTA, f'Envió el comunicado a {total} destinatario{"s" if total != 1 else ""} '
                                                     f'({resumen_por_tipo({t: len(i) for t, i in elegidos.items()})}).{programado}')
            if inmediato:
                from . import avisos
                transaction.on_commit(lambda: avisos.publicar(comunicado.pk))
    except IntegrityError:
        # La misma clave de envío llegó dos veces al mismo tiempo: la otra petición ya lo guardó
        previo = Comunicado.objects.filter(clave_envio=clave_envio, autor=autor).first()
        if previo is None:
            raise
        return previo, False
    return comunicado, True


def _nombre_de_archivo(nombre):
    nombre = (nombre or '').replace('\\', '/').rsplit('/', 1)[-1].strip()
    return (nombre or 'archivo')[:200]


# ---------------------------------------------------------------------------
# Corregir
# ---------------------------------------------------------------------------
def _pedir_otra_vez(comunicado, ahora):
    """Un cambio importante: lo respondido pasa al historial y quien respondió vuelve a tenerlo sin abrir. Devuelve cuántos."""
    respondieron = list(comunicado.destinatarios.filter(respondido_en__isnull=False).select_related('opcion').prefetch_related('autorizaciones__alumno'))
    RespuestaAnterior.objects.bulk_create([
        RespuestaAnterior(destinatario=copia, texto=copia.respuesta_detallada[:250], respondido_en=copia.respondido_en,
                          leido_en=copia.leido_en, retirada_en=ahora) for copia in respondieron
    ])
    Destinatario.objects.filter(pk__in=[copia.pk for copia in respondieron]).update(respuesta='', opcion=None, respondido_en=None, leido_en=None)
    AutorizacionEstudiante.objects.filter(destinatario__comunicado=comunicado).update(respuesta='', respondido_en=None)
    comunicado.reconfirmar_en = ahora
    return len(respondieron)


def editar(usuario, comunicado, *, titulo, descripcion, html='', urgente, expira, categoria='', fijado=False, evento=None,
           publicar_en=None, conservar_adjuntos=(), archivos=(), ahora=None, cambio='', responder_hasta=None, seleccion=None,
           publicar_ahora=False):
    """Corrige un comunicado ya enviado (ver arriba). Mientras siga programado se puede cambiar su hora de publicación, y
    también sus destinatarios (`seleccion`); publicarlo en ese momento se pide con `publicar_ahora`. `conservar_adjuntos`:
    los ids de sus archivos que se quedan; `archivos`, los nuevos; `cambio`: CAMBIO_MENOR o CAMBIO_IMPORTANTE, obligatorio
    si ya tiene respuestas. EnvioRechazado si no procede."""
    ahora = ahora or timezone.now()
    if not puede_editar(usuario, comunicado):
        raise EnvioRechazado('No puedes editar este comunicado.')
    con_respuestas = comunicado.pide_respuesta and comunicado.destinatarios.filter(respondido_en__isnull=False).exists()
    if con_respuestas and cambio not in (CAMBIO_MENOR, CAMBIO_IMPORTANTE):
        raise EnvioRechazado('Elige si es una corrección menor o un cambio importante.', 'cambio')
    sin_publicar = comunicado.avisado_en is None and comunicado.publicado_en > ahora
    publicado = comunicado.publicado_en
    if sin_publicar:
        if publicar_en is None and not publicar_ahora:
            raise EnvioRechazado('Elige la fecha y la hora de publicación, o marca que se publique al guardar.', 'publicar')
        publicado = _validar_publicacion(None if publicar_ahora else publicar_en, expira, ahora)
    elif expira is not None and expira != comunicado.expira and expira <= ahora:
        raise EnvioRechazado('La fecha de expiración debe ser posterior a este momento.', 'expira')
    if responder_hasta != comunicado.responder_hasta:
        _validar_plazo(responder_hasta, comunicado.respuesta, ahora, expira)
    alcance, elegidos = None, None
    if sin_publicar and seleccion is not None:
        alcance = alcance_de(usuario)
        try:
            elegidos = alcance.validar(seleccion)
        except FueraDeAlcance:
            raise EnvioRechazado('Algunas de las personas elegidas están fuera de los niveles a los que puedes enviar. Vuelve a '
                                 'elegir los destinatarios.', 'destinatarios') from None
        if not any(elegidos.values()):
            raise EnvioRechazado('Elige al menos un destinatario.', 'destinatarios')
    texto, limpio, imagenes = preparar_contenido(usuario, descripcion, html, comunicado=comunicado)
    datos_del_evento = validar_evento(**(evento or {}))
    categoria = _validar_categoria(categoria)
    conservar = set(comunicado.adjuntos.filter(pk__in=[int(pk) for pk in conservar_adjuntos if str(pk).isdigit()]).values_list('pk', flat=True))
    if len(conservar) + len(archivos) > Comunicado.MAXIMO_ADJUNTOS:
        raise EnvioRechazado(f'Adjunta como máximo {Comunicado.MAXIMO_ADJUNTOS} archivos.', 'archivos')

    publicar_ya = sin_publicar and publicar_ahora
    importante = con_respuestas and cambio == CAMBIO_IMPORTANTE
    with transaction.atomic():
        comunicado.titulo, comunicado.descripcion, comunicado.html = titulo, texto, limpio
        comunicado.urgente, comunicado.expira, comunicado.categoria, comunicado.fijado = urgente, expira, categoria, fijado
        for nombre, valor in datos_del_evento.items():
            setattr(comunicado, nombre, valor)
        comunicado.publicado_en, comunicado.responder_hasta = publicado, responder_hasta
        if not sin_publicar:   # sus destinatarios ya lo vieron: lo verán «Editado»
            comunicado.editado, comunicado.editado_por = ahora, usuario
        retiradas = _pedir_otra_vez(comunicado, ahora) if importante else 0
        comunicado.save()
        if elegidos is not None:   # nadie lo ha visto todavía: no hay lecturas que conservar
            comunicado.destinatarios.all().delete()
            _crear_destinatarios(comunicado, alcance, elegidos)
        # Las imágenes del texto: las nuevas pasan a ser suyas; las que ya no están se borran
        if imagenes:
            ImagenComunicado.objects.filter(pk__in=imagenes, comunicado__isnull=True, autor=usuario).update(comunicado=comunicado)
        sobrantes = list(comunicado.imagenes.exclude(pk__in=imagenes))
        for imagen in sobrantes:
            imagen.archivo.delete(save=False)
            imagen.delete()
        quitados = list(comunicado.adjuntos.exclude(pk__in=conservar))
        for adjunto in quitados:
            adjunto.archivo.delete(save=False)
            adjunto.delete()
        orden = (max(comunicado.adjuntos.values_list('orden', flat=True), default=-1)) + 1
        for archivo, tipo in archivos:
            Adjunto.objects.create(comunicado=comunicado, archivo=archivo, nombre_original=_nombre_de_archivo(archivo.name),
                                   tipo=tipo, tamano=archivo.size, orden=orden)
            orden += 1
        from Usuarios.seguridad import ACCION_CAMBIO, registrar
        nota = ' Lo publicó en ese momento.' if publicar_ya else ''
        if importante:
            nota = f' Cambio importante: pidió responder otra vez ({retiradas} respuesta{"s" if retiradas != 1 else ""} al historial).'
        registrar(usuario, comunicado, ACCION_CAMBIO, f'Corrigió el comunicado.{nota}')
        from . import avisos
        if publicar_ya:
            transaction.on_commit(lambda: avisos.publicar(comunicado.pk))
        elif importante:
            transaction.on_commit(lambda: avisos.avisar(comunicado.pk, cambio=True))
    return comunicado


# ---------------------------------------------------------------------------
# Quién lee
# ---------------------------------------------------------------------------
def _por_responder(ahora):
    """(De una copia) pide respuesta, no la ha dado y todavía se puede."""
    return (~Q(comunicado__respuesta='') & Q(respondido_en__isnull=True)
            & (Q(comunicado__responder_hasta__isnull=True) | Q(comunicado__responder_hasta__gt=ahora)))


def _por_atender(ahora):
    return Q(leido_en__isnull=True) | _por_responder(ahora)


@dataclass(frozen=True)
class Lector:
    """Una persona que recibe comunicados: un profesor o alguien del personal (con su cuenta del sistema), un estudiante o
    un tutor (con su portal)."""
    tipo: str
    persona: object

    @property
    def campo(self):
        return {Destinatario.ESTUDIANTE: 'alumno', Destinatario.TUTOR: 'tutor', Destinatario.PROFESOR: 'profesor',
                Destinatario.PERSONAL: 'usuario'}[self.tipo]

    def destinatarios(self, ahora=None):
        """Sus copias de los comunicados que puede ver: publicados, no eliminados ni caducados."""
        ahora = ahora or timezone.now()
        return Destinatario.objects.filter(**{self.campo: self.persona}, comunicado__eliminado=False,
                                           comunicado__publicado_en__lte=ahora).filter(
            Q(comunicado__expira__isnull=True) | Q(comunicado__expira__gt=ahora))

    def pendientes(self):
        """(por atender, urgentes por atender)"""
        conteo = self.destinatarios().filter(_por_atender(timezone.now())).aggregate(
            total=Count('pk'), urgentes=Count('pk', filter=Q(comunicado__urgente=True)))
        return conteo['total'] or 0, conteo['urgentes'] or 0


def lector_de_usuario(usuario):
    """Una cuenta del sistema con permiso para consultar comunicados: un profesor (si tiene ficha) o alguien del personal.
    Sin el permiso no recibe."""
    from Usuarios.docentes import profesor_de
    if not (usuario and usuario.is_authenticated and usuario.is_active and usuario.has_perm(RECIBIR)):
        return None
    profesor = profesor_de(usuario)
    return Lector(Destinatario.PROFESOR, profesor) if profesor is not None else Lector(Destinatario.PERSONAL, usuario)


def lector_de_portal(tipo, cuenta):
    from CISAHUAYO import portales
    return Lector(Destinatario.ESTUDIANTE if tipo == portales.ESTUDIANTE else Destinatario.TUTOR, cuenta)


def avisos(lector, limite=5):
    """Los comunicados por atender (los de la campana): primero los urgentes, luego del más reciente al más antiguo."""
    return list(lector.destinatarios().filter(_por_atender(timezone.now())).select_related('comunicado__autor')
                .order_by('-comunicado__urgente', '-comunicado__publicado_en', '-comunicado__pk')[:limite])


def marcar_leido(destinatario, ahora=None):
    """Guarda la primera lectura (si ya la tenía, no la cambia). Devuelve True si fue la primera."""
    if destinatario.leido_en is not None:
        return False
    ahora = ahora or timezone.now()
    if Destinatario.objects.filter(pk=destinatario.pk, leido_en__isnull=True).update(leido_en=ahora):
        destinatario.leido_en = ahora
        return True
    destinatario.refresh_from_db(fields=['leido_en'])
    return False


def _responder_por_estudiante(filas, valor, por_estudiante):
    """La respuesta del tutor con lo que eligió por cada hijo (`por_estudiante`: {id de estudiante: 'si' o 'no'}; `valor`
    vale para los que no estén ahí). Guarda cada fila y devuelve lo que queda en su destinatario."""
    elegidas = {}
    for fila in filas:
        eleccion = str((por_estudiante or {}).get(fila.alumno_id, valor) or '').strip().lower()
        if eleccion not in ('si', 'no'):
            raise EnvioRechazado('Responde por cada estudiante.' if len(filas) > 1 else 'Elige Sí o No.')
        elegidas[fila] = Destinatario.RESPUESTA_SI if eleccion == 'si' else Destinatario.RESPUESTA_NO
    return elegidas


def responder(destinatario, valor, ahora=None, por_estudiante=None):
    """Guarda la respuesta del destinatario: 'enterado', 'si' / 'no' (`por_estudiante`, si un tutor responde distinto por
    cada hijo) o el id de una opción de la encuesta. Responder cuenta también como abrirlo. EnvioRechazado si no procede."""
    ahora = ahora or timezone.now()
    comunicado = destinatario.comunicado
    valor = str(valor or '').strip().lower()
    if not comunicado.pide_respuesta:
        raise EnvioRechazado('Este comunicado no pide respuesta.')
    if comunicado.caducado:
        raise EnvioRechazado('Este comunicado ya caducó: ya no se puede responder.')
    if comunicado.plazo_terminado_en(ahora):
        raise EnvioRechazado('El plazo para responder ya terminó.')
    opcion, elegidas = None, {}
    if comunicado.respuesta == Comunicado.ENTERADO:
        if valor != 'enterado':
            raise EnvioRechazado('Elige una respuesta.')
        respuesta = Destinatario.RESPUESTA_ENTERADO
    elif comunicado.respuesta == Comunicado.AUTORIZACION:
        filas = list(destinatario.autorizaciones.all())
        if filas:
            elegidas = _responder_por_estudiante(filas, valor, por_estudiante)
            distintas = set(elegidas.values())
            respuesta = distintas.pop() if len(distintas) == 1 else Destinatario.RESPUESTA_MIXTA
        else:
            if valor not in ('si', 'no'):
                raise EnvioRechazado('Elige Sí o No.')
            respuesta = Destinatario.RESPUESTA_SI if valor == 'si' else Destinatario.RESPUESTA_NO
    else:
        opcion = comunicado.opciones.filter(pk=valor).first() if valor.isdigit() else None
        if opcion is None:
            raise EnvioRechazado('Elige una de las opciones.')
        respuesta = Destinatario.RESPUESTA_OPCION
    cambios = {'respuesta': respuesta, 'opcion': opcion, 'respondido_en': ahora}
    if destinatario.leido_en is None:
        cambios['leido_en'] = ahora
    with transaction.atomic():
        for fila, eleccion in elegidas.items():
            AutorizacionEstudiante.objects.filter(pk=fila.pk).update(respuesta=eleccion, respondido_en=ahora)
        Destinatario.objects.filter(pk=destinatario.pk).update(**cambios)
    for nombre, valor_nuevo in cambios.items():
        setattr(destinatario, nombre, valor_nuevo)
    return destinatario


def recibidos(lector, estado='todos', categoria=''):
    """Sus copias: primero los urgentes sin abrir, luego lo que espera su respuesta, los fijados y después del más reciente
    al más antiguo."""
    ahora = timezone.now()
    adjuntos = Adjunto.objects.filter(comunicado=OuterRef('comunicado')).order_by().values('comunicado').annotate(n=Count('pk')).values('n')
    consulta = lector.destinatarios().select_related('comunicado__autor').annotate(
        adjuntos=Coalesce(Subquery(adjuntos, output_field=IntegerField()), 0),
        prioridad=Case(When(leido_en__isnull=True, comunicado__urgente=True, then=Value(0)), When(_por_responder(ahora), then=Value(1)),
                       When(comunicado__fijado=True, then=Value(2)), default=Value(3), output_field=IntegerField()),
    )
    if estado == 'pendientes':
        consulta = consulta.filter(leido_en__isnull=True)
    elif estado == 'leidos':
        consulta = consulta.filter(leido_en__isnull=False)
    elif estado == 'por_responder':
        consulta = consulta.filter(_por_responder(ahora))
    elif estado == 'por_atender':
        consulta = consulta.filter(_por_atender(ahora))
    if categoria:
        consulta = consulta.filter(comunicado__categoria=categoria)
    return consulta.order_by('prioridad', '-comunicado__publicado_en', '-comunicado__pk')


def estado_de(copia, ahora=None):
    """(clave, texto, icono) de lo que una copia pide de quien la recibe: la pantalla nunca lo dice solo con color."""
    ahora = ahora or timezone.now()
    comunicado = copia.comunicado
    if copia.leido_en is None and comunicado.urgente:
        return 'urgente', 'Urgente · Sin abrir', 'triangle-alert'
    if comunicado.pide_respuesta and copia.respondido_en is None:
        if comunicado.plazo_terminado_en(ahora):
            return 'plazo', 'Plazo terminado', 'clock'
        if comunicado.responder_hasta:
            return 'responder', f'Responde antes del {date_format(timezone.localtime(comunicado.responder_hasta), "j b")}', 'clipboard-check'
        return 'responder', 'Por responder', 'clipboard-check'
    if copia.leido_en is None:
        return 'sin_abrir', 'Sin abrir', 'eye-off'
    if comunicado.pide_respuesta:
        return 'confirmado', 'Confirmado' if comunicado.respuesta == Comunicado.ENTERADO else 'Respondido', 'circle-check'
    return 'abierto', 'Abierto', 'check'


# ---------------------------------------------------------------------------
# Gestión y seguimiento
# ---------------------------------------------------------------------------
def con_estadisticas(consulta):
    """Los comunicados con su total de destinatarios, cuántos lo abrieron y respondieron, cuántos no pueden abrirlo por no
    tener acceso a su portal y cuántos hay de cada tipo (cada destinatario es una persona distinta: el envío no admite
    repetidos). Los archivos se cuentan aparte para no multiplicar filas."""
    adjuntos = Adjunto.objects.filter(comunicado=OuterRef('pk')).order_by().values('comunicado').annotate(n=Count('pk')).values('n')
    return consulta.annotate(
        total=Count('destinatarios'),
        leidos=Count('destinatarios', filter=Q(destinatarios__leido_en__isnull=False)),
        respondidos=Count('destinatarios', filter=Q(destinatarios__respondido_en__isnull=False)),
        n_sin_acceso=Count('destinatarios', filter=sin_acceso_al_portal('destinatarios__') & Q(destinatarios__leido_en__isnull=True)),
        n_tutores=Count('destinatarios', filter=Q(destinatarios__tipo=Destinatario.TUTOR)),
        n_estudiantes=Count('destinatarios', filter=Q(destinatarios__tipo=Destinatario.ESTUDIANTE)),
        n_profesores=Count('destinatarios', filter=Q(destinatarios__tipo=Destinatario.PROFESOR)),
        n_personal=Count('destinatarios', filter=Q(destinatarios__tipo=Destinatario.PERSONAL)),
        n_adjuntos=Coalesce(Subquery(adjuntos, output_field=IntegerField()), 0),
    )


def preparar(comunicado):
    """Agrega a un comunicado con estadísticas lo que muestran la tarjeta y el detalle."""
    conteos = {Destinatario.TUTOR: comunicado.n_tutores, Destinatario.ESTUDIANTE: comunicado.n_estudiantes,
               Destinatario.PROFESOR: comunicado.n_profesores, Destinatario.PERSONAL: comunicado.n_personal}
    comunicado.resumen_destinatarios = resumen_por_tipo(conteos)
    comunicado.desglose = [(tipo, conteos[tipo], cantidad(conteos[tipo], tipo)) for tipo in ORDEN_DE_TIPOS if conteos[tipo]]
    # Quien no tiene acceso a su portal y no lo ha abierto no cuenta: no hay nada que esperar de esa persona
    comunicado.alcanzables = comunicado.total - comunicado.n_sin_acceso
    comunicado.porcentaje = porcentaje(comunicado.leidos, comunicado.alcanzables)
    comunicado.pendientes = comunicado.alcanzables - comunicado.leidos
    comunicado.porcentaje_respuesta = porcentaje(comunicado.respondidos, comunicado.alcanzables)
    comunicado.sin_responder = comunicado.alcanzables - comunicado.respondidos
    comunicado.faltan = comunicado.sin_responder if comunicado.pide_respuesta else comunicado.pendientes
    return comunicado


def gestionables(usuario, vista):
    """'enviados': los propios; 'gestion': todos los del colegio (solo el administrador)."""
    consulta = Comunicado.objects.visibles().select_related('autor')
    if vista == 'gestion' and es_administrador(usuario):
        return consulta
    return consulta.filter(autor=usuario)


def filtrar_por_estado(consulta, estado, ahora=None):
    ahora = ahora or timezone.now()
    if estado == 'activos':
        return consulta.activos(ahora).publicados(ahora)
    if estado == 'programados':
        return consulta.filter(publicado_en__gt=ahora)
    if estado == 'caducados':
        return consulta.caducados(ahora)
    if estado == 'con_pendientes':
        faltan = Destinatario.objects.filter(comunicado=OuterRef('pk')).exclude(sin_acceso_al_portal()).filter(
            Q(comunicado__respuesta='', leido_en__isnull=True) | (~Q(comunicado__respuesta='') & Q(respondido_en__isnull=True)))
        return consulta.activos(ahora).publicados(ahora).filter(Exists(faltan))
    return consulta


def buscar(consulta, texto, campos=('titulo', 'descripcion')):
    for palabra in (texto or '').split():
        condicion = Q()
        for campo in campos:
            condicion |= Q(**{f'{campo}__icontains': palabra})
        consulta = consulta.filter(condicion)
    return consulta


def puede_dar_seguimiento(usuario, comunicado):
    return es_administrador(usuario) or (comunicado.autor_id == usuario.pk and usuario.has_perm(SEGUIMIENTO))


def puede_eliminar(usuario, comunicado):
    return es_administrador(usuario) or (comunicado.autor_id == usuario.pk and usuario.has_perm(ELIMINAR))


def puede_editar(usuario, comunicado):
    return not comunicado.eliminado and (es_administrador(usuario) or (comunicado.autor_id == usuario.pk and usuario.has_perm(ENVIAR)))


def autorizaciones_por_estudiante(comunicado):
    """[{alumno_id, nombre, grupo, clave, texto, tutores}] de una autorización, una fila por estudiante, por grupo y nombre.
    `clave`: autorizado, no_autorizado, desacuerdo (sus tutores se contradicen: no cuenta como autorizado), sin_responder o
    sin_acceso (ningún tutor suyo puede entrar a su portal). `tutores`: [(nombre, respuesta)]."""
    filas = (AutorizacionEstudiante.objects.filter(destinatario__comunicado=comunicado).order_by()
             .select_related('alumno', 'destinatario__tutor'))
    por_alumno = {}
    for fila in filas:
        por_alumno.setdefault(fila.alumno_id, []).append(fila)
    if not por_alumno:
        return []
    ciclo = ciclo_actual()
    inscripciones = Inscripcion.objects.filter(ciclo=ciclo, activa=True, alumno__in=list(por_alumno)).select_related('grupo__nombre', 'grupo__grado')
    grupos = {inscripcion.alumno_id: inscripcion.grupo.corto for inscripcion in inscripciones}
    textos = {'autorizado': 'Autorizado', 'no_autorizado': 'No autorizado', 'desacuerdo': 'Tutores en desacuerdo',
              'sin_responder': 'Sin responder', 'sin_acceso': 'Sin acceso al portal'}
    resultado = []
    for alumno_id, propias in por_alumno.items():
        respuestas = {fila.respuesta for fila in propias if fila.respuesta}
        if len(respuestas) > 1:
            clave = 'desacuerdo'
        elif respuestas:
            clave = 'autorizado' if Destinatario.RESPUESTA_SI in respuestas else 'no_autorizado'
        else:
            clave = 'sin_acceso' if all(fila.destinatario.sin_acceso for fila in propias) else 'sin_responder'
        resultado.append({
            'alumno_id': alumno_id, 'nombre': propias[0].alumno.nombre_completo, 'grupo': grupos.get(alumno_id, ''), 'clave': clave,
            'texto': textos[clave],
            'tutores': [(fila.destinatario.nombre, {'SI': 'Sí', 'NO': 'No'}.get(fila.respuesta, 'Sin responder')) for fila in propias],
        })
    resultado.sort(key=lambda fila: (fila['grupo'], fila['nombre'].lower()))
    return resultado


def resumen_de_respuestas(comunicado, destinatarios):
    """[{texto, cuantos, porcentaje}] de las respuestas (una fila por respuesta posible) y cuántos no han respondido, sin
    contar a quien no tiene acceso a su portal y no lo ha abierto. Una autorización se cuenta por estudiante."""
    por_estudiante = autorizaciones_por_estudiante(comunicado) if comunicado.respuesta == Comunicado.AUTORIZACION else []
    if por_estudiante:
        contar = lambda clave: sum(fila['clave'] == clave for fila in por_estudiante)   # noqa: E731
        sin_responder = contar('sin_responder')
        total = len(por_estudiante) - contar('sin_acceso')
        filas = [('Sí autoriza', contar('autorizado')), ('No autoriza', contar('no_autorizado'))]
        if contar('desacuerdo'):
            filas.append(('Tutores en desacuerdo', contar('desacuerdo')))
        return {
            'filas': [{'texto': texto, 'cuantos': n, 'porcentaje': porcentaje(n, total)} for texto, n in filas], 'sin_responder': sin_responder,
            'respondieron': total - sin_responder, 'total': total, 'por_estudiante': True,
        }
    total = sum(1 for d in destinatarios if d.leido or not d.sin_acceso)
    respondieron = [d for d in destinatarios if d.respondio]
    if comunicado.respuesta == Comunicado.ENTERADO:
        filas = [('Enterado', len(respondieron))]
    elif comunicado.respuesta == Comunicado.AUTORIZACION:
        filas = [('Sí autoriza', sum(d.respuesta == Destinatario.RESPUESTA_SI for d in respondieron)),
                 ('No autoriza', sum(d.respuesta == Destinatario.RESPUESTA_NO for d in respondieron))]
    else:
        filas = [(opcion.texto, sum(d.opcion_id == opcion.pk for d in respondieron)) for opcion in comunicado.opciones.all()]
    return {
        'filas': [{'texto': texto, 'cuantos': n, 'porcentaje': porcentaje(n, total)} for texto, n in filas],
        'sin_responder': total - len(respondieron), 'respondieron': len(respondieron), 'total': total,
    }


def lectura_por_grupo(destinatarios):
    """[{nombre, total, leidos, porcentaje, respondidos, sin_acceso}] por grupo (el que tenía cada estudiante y el primer hijo
    de cada tutor al enviarse), y aparte los profesores, el personal y quien no tenía grupo. `total` no cuenta a quien no
    tiene acceso a su portal y no lo ha abierto: esas personas van en `sin_acceso`."""
    filas = {}
    for destinatario in destinatarios:
        if destinatario.tipo == Destinatario.PROFESOR:
            clave, nombre, orden = 'profesores', 'Profesores', (90,)
        elif destinatario.tipo == Destinatario.PERSONAL:
            clave, nombre, orden = 'personal', 'Personal del colegio', (91,)
        elif destinatario.grupo_id is None:
            clave, nombre, orden = 'sin', 'Sin grupo', (92,)
        else:
            grupo = destinatario.grupo
            nivel = grupo.grado.nivel
            clave = grupo.pk
            nombre = f'{grupo.corto} · {grupo.grado.get_nivel_display()}'
            orden = (ORDEN_NIVELES.index(nivel) if nivel in ORDEN_NIVELES else 9, grupo.grado.numero, nombre)
        fila = filas.setdefault(clave, {'nombre': nombre, 'orden': orden, 'total': 0, 'leidos': 0, 'respondidos': 0, 'sin_acceso': 0})
        if destinatario.sin_acceso and not destinatario.leido:
            fila['sin_acceso'] += 1
            continue
        fila['total'] += 1
        fila['leidos'] += destinatario.leido
        fila['respondidos'] += destinatario.respondio
    resultado = sorted(filas.values(), key=lambda fila: fila['orden'])
    for fila in resultado:
        fila['porcentaje'] = porcentaje(fila['leidos'], fila['total'])
        fila['porcentaje_respuesta'] = porcentaje(fila['respondidos'], fila['total'])
        fila['es_grupo'] = fila['orden'][0] < 90
    return resultado


# ---------------------------------------------------------------------------
# Recordar a los pendientes
# ---------------------------------------------------------------------------
def por_recordar(comunicado):
    """Quienes no lo han abierto (o no han respondido, si pide respuesta) y tienen cómo entrar a su portal."""
    faltan = Q(respondido_en__isnull=True) if comunicado.pide_respuesta else Q(leido_en__isnull=True)
    return comunicado.destinatarios.filter(faltan).exclude(sin_acceso_al_portal())


def motivo_para_no_recordar(comunicado, ahora=None):
    """Por qué no se puede recordar ahora (texto), o '' si se puede."""
    ahora = ahora or timezone.now()
    if comunicado.eliminado or comunicado.caducado_en(ahora):
        return 'El comunicado ya no está activo.'
    if comunicado.publicado_en > ahora:
        return 'Todavía no se publica.'
    if comunicado.plazo_terminado_en(ahora):
        return 'El plazo para responder ya terminó.'
    if comunicado.recordado_en and ahora - comunicado.recordado_en < ESPERA_ENTRE_RECORDATORIOS:
        siguiente = timezone.localtime(comunicado.recordado_en + ESPERA_ENTRE_RECORDATORIOS)
        return f'Ya se recordó hace poco. Podrás volver a recordarlo a las {siguiente:%H:%M}.'
    if not por_recordar(comunicado).exists():
        return 'Todos lo han respondido.' if comunicado.pide_respuesta else 'Todos lo han abierto.'
    return ''


def recordar(usuario, comunicado, ahora=None):
    """Vuelve a avisar (en tiempo real y push, como recordatorio) a los pendientes. Una vez por hora como máximo.
    Devuelve a cuántos. EnvioRechazado si no procede."""
    ahora = ahora or timezone.now()
    if not puede_dar_seguimiento(usuario, comunicado):
        raise EnvioRechazado('No puedes dar seguimiento a este comunicado.')
    motivo = motivo_para_no_recordar(comunicado, ahora)
    if motivo:
        raise EnvioRechazado(motivo)
    ids = list(por_recordar(comunicado).values_list('pk', flat=True))
    with transaction.atomic():
        disponible = Q(recordado_en__isnull=True) | Q(recordado_en__lte=ahora - ESPERA_ENTRE_RECORDATORIOS)
        if not Comunicado.objects.filter(disponible, pk=comunicado.pk).update(recordado_en=ahora, recordatorios=comunicado.recordatorios + 1):
            raise EnvioRechazado('Ya se recordó hace poco.')
        comunicado.recordado_en, comunicado.recordatorios = ahora, comunicado.recordatorios + 1
        from Usuarios.seguridad import ACCION_CAMBIO, registrar
        registrar(usuario, comunicado, ACCION_CAMBIO, f'Recordó el comunicado a {len(ids)} pendiente{"s" if len(ids) != 1 else ""}.')
        from . import avisos
        transaction.on_commit(lambda: avisos.avisar(comunicado.pk, solo=ids, recordatorio=True))
    return len(ids)


# ---------------------------------------------------------------------------
# Eliminar
# ---------------------------------------------------------------------------
def eliminar(usuario, comunicado):
    """Eliminación lógica: deja de verse para todos y queda registrada (quién y cuándo) para la auditoría."""
    if comunicado.eliminado:
        return False
    from Usuarios.seguridad import ACCION_BAJA, registrar
    with transaction.atomic():
        actualizados = Comunicado.objects.filter(pk=comunicado.pk, eliminado=False).update(
            eliminado=True, eliminado_en=timezone.now(), eliminado_por=usuario)
        if actualizados:
            registrar(usuario, comunicado, ACCION_BAJA, 'Eliminó el comunicado (se conserva para auditoría).')
    comunicado.eliminado = bool(actualizados) or comunicado.eliminado
    return bool(actualizados)


# ---------------------------------------------------------------------------
# «Agregar a mi calendario» (.ics)
# ---------------------------------------------------------------------------
def calendario_ics(comunicado, url=''):
    """El evento del comunicado como archivo de calendario (CISAHUAYO/ics.py: iPhone, Android, Outlook y Google lo abren)."""
    from CISAHUAYO.ics import EventoIcs, calendario
    return calendario([EventoIcs(
        uid=f'comunicado-{comunicado.pk}@cisahuayo', titulo=comunicado.titulo, fecha_inicio=comunicado.evento_fecha,
        hora_inicio=comunicado.evento_hora_inicio, hora_fin=comunicado.evento_hora_fin, descripcion=comunicado.descripcion,
        lugar=comunicado.evento_lugar, url=url,
    )])


def eventos_para_la_agenda(lector=None, autor=None, desde=None, hasta=None):
    """Los comunicados con evento entre esas fechas que ve esa persona: los que recibe (publicados y activos) y, si es del
    sistema, los que envió. Sin repetidos."""
    vistos, resultado = set(), []
    if lector is not None:
        for copia in lector.destinatarios().filter(comunicado__evento_fecha__range=(desde, hasta)).select_related('comunicado'):
            vistos.add(copia.comunicado_id)
            resultado.append((copia.comunicado, lector.tipo))
    if autor is not None:
        for comunicado in Comunicado.objects.visibles().filter(autor=autor, evento_fecha__range=(desde, hasta)).exclude(pk__in=vistos):
            resultado.append((comunicado, None))
    return resultado
