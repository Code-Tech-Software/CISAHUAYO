"""Las operaciones de los comunicados: enviar, corregir, leer, responder, listar, dar seguimiento, recordar y eliminar.

- Enviar: lo valida todo en el servidor (alcance de quien envía, destinatarios, fechas de publicación y de expiración,
  respuesta que se pide, evento) y lo guarda de una sola vez (comunicado, destinatarios, opciones, archivos e imágenes
  del texto). La `clave_envio` que trae el formulario hace que un doble clic o un reintento devuelvan el mismo
  comunicado en lugar de crear otro. El aviso sale en segundo plano (Comunicados/avisos.py); si se programó, al llegar
  su hora.
- Corregir (2026-10-27): el autor (o el administrador) cambia el texto, el título, la urgencia, la expiración, la
  categoría, si va fijado, el evento y los archivos; los destinatarios y la respuesta que se pide no cambian (las
  lecturas y las respuestas se conservan). Queda «Editado» para quien lo recibe y en el historial.
- Leer: la primera vez que el destinatario abre el detalle se guarda la fecha y hora; abrirlo otra vez no la cambia.
  Ver la tarjeta, recibir el aviso o que el autor o el administrador consulten el seguimiento no cuenta como lectura.
- Responder (2026-10-27): «Enterado», Sí o No a una autorización, o una opción de una encuesta. Se puede cambiar
  mientras el comunicado siga activo (lo último que eligió es lo que cuenta).
- Publicar y caducar: un comunicado programado no se ve antes de su hora, y uno con fecha de expiración ya cumplida deja
  de verse y de abrirse para sus destinatarios (aun con un enlace directo); se compara con la hora del servidor en cada
  consulta. El autor y el administrador conservan el histórico con sus estadísticas.
- Gestionar: el administrador, todos; los demás, solo los suyos (pertenecer al mismo nivel no deja ver los de otros).
"""
from dataclasses import dataclass
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe

from Alumnos.models import ORDEN_NIVELES
from Mensajes import enriquecido

from .alcance import ELIMINAR, ENVIAR, RECIBIR, SEGUIMIENTO, SIN_NIVELES, FueraDeAlcance, alcance_de, es_administrador
from .models import Adjunto, Comunicado, Destinatario, ImagenComunicado, OpcionEncuesta

PLURAL = {Destinatario.TUTOR: ('tutor', 'tutores'), Destinatario.ESTUDIANTE: ('estudiante', 'estudiantes'),
          Destinatario.PROFESOR: ('profesor', 'profesores'), Destinatario.PERSONAL: ('persona del personal', 'personas del personal')}
ORDEN_DE_TIPOS = (Destinatario.TUTOR, Destinatario.ESTUDIANTE, Destinatario.PROFESOR, Destinatario.PERSONAL)
PROGRAMAR_HASTA = timedelta(days=180)
ESPERA_ENTRE_RECORDATORIOS = timedelta(hours=1)


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
           categoria='', fijado=False, publicar_en=None, respuesta='', pregunta='', opciones=(), evento=None, copiar_adjuntos=()):
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

    detalles = alcance.detalles(elegidos)
    grupos = alcance.grupos_de(elegidos)
    campo = {Destinatario.ESTUDIANTE: 'alumno_id', Destinatario.TUTOR: 'tutor_id', Destinatario.PROFESOR: 'profesor_id',
             Destinatario.PERSONAL: 'usuario_id'}
    inmediato = publicar_en is None
    try:
        with transaction.atomic():
            comunicado = Comunicado.objects.create(
                titulo=titulo, descripcion=texto, html=limpio, urgente=urgente, expira=expira, autor=autor,
                rol_autor=rol_visible(autor)[:80], creado=ahora, publicado_en=publicado, avisado_en=ahora if inmediato else None,
                clave_envio=clave_envio, categoria=categoria, fijado=fijado, respuesta=respuesta, pregunta=pregunta,
                **datos_del_evento,
            )
            Destinatario.objects.bulk_create([
                Destinatario(comunicado=comunicado, tipo=tipo, detalle=detalles[tipo].get(pk, '')[:250],
                             grupo_id=grupos.get(tipo, {}).get(pk), **{campo[tipo]: pk})
                for tipo in ORDEN_DE_TIPOS for pk in sorted(elegidos.get(tipo, ()))
            ])
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
                transaction.on_commit(lambda: avisos.avisar(comunicado.pk))
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
def editar(usuario, comunicado, *, titulo, descripcion, html='', urgente, expira, categoria='', fijado=False, evento=None,
           publicar_en=None, conservar_adjuntos=(), archivos=(), ahora=None):
    """Corrige un comunicado ya enviado (ver arriba). Mientras siga programado se puede cambiar su hora de publicación
    (sin hora: se publica en ese momento). `conservar_adjuntos`: los ids de sus archivos que se quedan; `archivos`, los
    nuevos. EnvioRechazado si no procede."""
    ahora = ahora or timezone.now()
    if not puede_editar(usuario, comunicado):
        raise EnvioRechazado('No puedes editar este comunicado.')
    sin_publicar = comunicado.avisado_en is None and comunicado.publicado_en > ahora
    publicado = comunicado.publicado_en
    if sin_publicar:
        publicado = _validar_publicacion(publicar_en, expira, ahora)
    elif expira is not None and expira <= ahora:
        raise EnvioRechazado('La fecha de expiración debe ser posterior a este momento.', 'expira')
    texto, limpio, imagenes = preparar_contenido(usuario, descripcion, html, comunicado=comunicado)
    datos_del_evento = validar_evento(**(evento or {}))
    categoria = _validar_categoria(categoria)
    conservar = set(comunicado.adjuntos.filter(pk__in=[int(pk) for pk in conservar_adjuntos if str(pk).isdigit()]).values_list('pk', flat=True))
    if len(conservar) + len(archivos) > Comunicado.MAXIMO_ADJUNTOS:
        raise EnvioRechazado(f'Adjunta como máximo {Comunicado.MAXIMO_ADJUNTOS} archivos.', 'archivos')

    publicar_ya = sin_publicar and publicar_en is None
    with transaction.atomic():
        comunicado.titulo, comunicado.descripcion, comunicado.html = titulo, texto, limpio
        comunicado.urgente, comunicado.expira, comunicado.categoria, comunicado.fijado = urgente, expira, categoria, fijado
        for nombre, valor in datos_del_evento.items():
            setattr(comunicado, nombre, valor)
        comunicado.publicado_en = publicado
        if publicar_ya:
            comunicado.avisado_en = ahora
        if not sin_publicar:   # sus destinatarios ya lo vieron: lo verán «Editado»
            comunicado.editado, comunicado.editado_por = ahora, usuario
        comunicado.save()
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
        registrar(usuario, comunicado, ACCION_CAMBIO, 'Corrigió el comunicado.' + (' Lo publicó en ese momento.' if publicar_ya else ''))
        if publicar_ya:
            from . import avisos
            transaction.on_commit(lambda: avisos.avisar(comunicado.pk))
    return comunicado


# ---------------------------------------------------------------------------
# Quién lee
# ---------------------------------------------------------------------------
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
        """(sin leer, urgentes sin leer)"""
        conteo = self.destinatarios().filter(leido_en__isnull=True).aggregate(
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
    """Los comunicados que aún no lee (los de la campana): primero los urgentes, luego del más reciente al más antiguo."""
    return list(lector.destinatarios().filter(leido_en__isnull=True).select_related('comunicado__autor')
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


def responder(destinatario, valor, ahora=None):
    """Guarda la respuesta del destinatario: 'enterado', 'si' / 'no' o el id de una opción de la encuesta. Responder
    cuenta también como leerlo. EnvioRechazado si no procede."""
    ahora = ahora or timezone.now()
    comunicado = destinatario.comunicado
    valor = str(valor or '').strip().lower()
    if not comunicado.pide_respuesta:
        raise EnvioRechazado('Este comunicado no pide respuesta.')
    if comunicado.caducado:
        raise EnvioRechazado('Este comunicado ya caducó: ya no se puede responder.')
    opcion = None
    if comunicado.respuesta == Comunicado.ENTERADO:
        if valor != 'enterado':
            raise EnvioRechazado('Elige una respuesta.')
        respuesta = Destinatario.RESPUESTA_ENTERADO
    elif comunicado.respuesta == Comunicado.AUTORIZACION:
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
    Destinatario.objects.filter(pk=destinatario.pk).update(**cambios)
    for nombre, valor_nuevo in cambios.items():
        setattr(destinatario, nombre, valor_nuevo)
    return destinatario


def recibidos(lector, estado='todos', categoria=''):
    """Sus copias: primero los urgentes sin leer, luego los fijados y después del más reciente al más antiguo."""
    adjuntos = Adjunto.objects.filter(comunicado=OuterRef('comunicado')).order_by().values('comunicado').annotate(n=Count('pk')).values('n')
    consulta = lector.destinatarios().select_related('comunicado__autor').annotate(
        adjuntos=Coalesce(Subquery(adjuntos, output_field=IntegerField()), 0),
        prioridad=Case(When(leido_en__isnull=True, comunicado__urgente=True, then=Value(0)),
                       When(comunicado__fijado=True, then=Value(1)), default=Value(2), output_field=IntegerField()),
    )
    if estado == 'pendientes':
        consulta = consulta.filter(leido_en__isnull=True)
    elif estado == 'leidos':
        consulta = consulta.filter(leido_en__isnull=False)
    elif estado == 'por_responder':
        consulta = consulta.exclude(comunicado__respuesta='').filter(respondido_en__isnull=True)
    if categoria:
        consulta = consulta.filter(comunicado__categoria=categoria)
    return consulta.order_by('prioridad', '-comunicado__publicado_en', '-comunicado__pk')


# ---------------------------------------------------------------------------
# Gestión y seguimiento
# ---------------------------------------------------------------------------
def con_estadisticas(consulta):
    """Los comunicados con su total de destinatarios, cuántos lo leyeron y respondieron y cuántos hay de cada tipo (cada
    destinatario es una persona distinta: el envío no admite repetidos). Los archivos se cuentan aparte para no
    multiplicar filas."""
    adjuntos = Adjunto.objects.filter(comunicado=OuterRef('pk')).order_by().values('comunicado').annotate(n=Count('pk')).values('n')
    return consulta.annotate(
        total=Count('destinatarios'),
        leidos=Count('destinatarios', filter=Q(destinatarios__leido_en__isnull=False)),
        respondidos=Count('destinatarios', filter=Q(destinatarios__respondido_en__isnull=False)),
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
    comunicado.porcentaje = porcentaje(comunicado.leidos, comunicado.total)
    comunicado.pendientes = comunicado.total - comunicado.leidos
    comunicado.porcentaje_respuesta = porcentaje(comunicado.respondidos, comunicado.total)
    comunicado.sin_responder = comunicado.total - comunicado.respondidos
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


def resumen_de_respuestas(comunicado, destinatarios):
    """[{texto, cuantos, porcentaje}] de las respuestas (una fila por respuesta posible) y cuántos no han respondido."""
    total = len(destinatarios)
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
    """[{nombre, total, leidos, porcentaje, respondidos}] por grupo (el que tenía cada estudiante y el primer hijo de cada
    tutor al enviarse), y aparte los profesores, el personal y quien no tenía grupo."""
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
        fila = filas.setdefault(clave, {'nombre': nombre, 'orden': orden, 'total': 0, 'leidos': 0, 'respondidos': 0})
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
    """Quienes no lo han leído (o no han respondido, si pide respuesta)."""
    if comunicado.pide_respuesta:
        return comunicado.destinatarios.filter(respondido_en__isnull=True)
    return comunicado.destinatarios.filter(leido_en__isnull=True)


def motivo_para_no_recordar(comunicado, ahora=None):
    """Por qué no se puede recordar ahora (texto), o '' si se puede."""
    ahora = ahora or timezone.now()
    if comunicado.eliminado or comunicado.caducado_en(ahora):
        return 'El comunicado ya no está activo.'
    if comunicado.publicado_en > ahora:
        return 'Todavía no se publica.'
    if comunicado.recordado_en and ahora - comunicado.recordado_en < ESPERA_ENTRE_RECORDATORIOS:
        siguiente = timezone.localtime(comunicado.recordado_en + ESPERA_ENTRE_RECORDATORIOS)
        return f'Ya se recordó hace poco. Podrás volver a recordarlo a las {siguiente:%H:%M}.'
    if not por_recordar(comunicado).exists():
        return 'Todos lo han respondido.' if comunicado.pide_respuesta else 'Todos lo han leído.'
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
