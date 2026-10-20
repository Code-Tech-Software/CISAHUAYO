"""Quién puede escribirle a quién, y las operaciones de la mensajería (conversar, enviar, leer, bandeja y avisos).

Las cuentas siguen separadas: un usuario del sistema, un estudiante y un tutor solo se encuentran a través de un
`Participante`, y solo pueden conversar estas parejas (en ambos sentidos):
- Dos usuarios del sistema con la mensajería (`Mensajes.usar` o `Mensajes.contactar_familias`).
- Un docente y los estudiantes de los grupos donde imparte una materia en el ciclo actual, y los tutores de esos
  estudiantes (vínculo activo).
- Quien atiende a las familias (`Mensajes.contactar_familias`) y cualquier estudiante o tutor; una cuenta de
  prefectura, solo los de su alcance (Prefectura/alcance.py).
Nunca entre estudiantes, entre tutores, ni entre un estudiante y un tutor. Una cuenta inactiva (usuario desactivado,
estudiante o tutor sin acceso al portal) no aparece ni recibe mensajes nuevos. Si la relación deja de existir (cambio
de grupo, fin del ciclo), la conversación se conserva para consulta pero ya no admite mensajes nuevos.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from Alumnos.academico import ciclo_actual
from Alumnos.models import Alumno, Inscripcion, MateriaGrado, Tutor, TutorAlumno
from CISAHUAYO import portales

from . import enriquecido
from .models import Conversacion, ImagenMensaje, Mensaje, Miembro, Participante

USAR = 'Mensajes.usar'
FAMILIAS = 'Mensajes.contactar_familias'
# El espacio de rutas de cada clase de cuenta (las mismas vistas en el sistema y en los dos portales)
ESPACIO = {
    Participante.SISTEMA: 'mensajes',
    Participante.ESTUDIANTE: 'portal_estudiantes:mensajes',
    Participante.TUTOR: 'portal_tutores:mensajes',
}
VISTA_PREVIA = 120


# ---------------------------------------------------------------------------
# Participantes
# ---------------------------------------------------------------------------
def usa_mensajeria(usuario):
    return bool(usuario and usuario.is_authenticated and usuario.is_active and (usuario.has_perm(USAR) or usuario.has_perm(FAMILIAS)))


def _obtener(campo, cuenta, tipo, crear):
    participante = Participante.objects.filter(**{campo: cuenta}).first()
    if participante is None and crear:
        try:
            with transaction.atomic():
                participante = Participante.objects.create(tipo=tipo, **{campo: cuenta})
        except IntegrityError:   # otra petición lo creó al mismo tiempo
            participante = Participante.objects.get(**{campo: cuenta})
    return participante


def de_usuario(usuario, crear=True):
    return _obtener('usuario', usuario, Participante.SISTEMA, crear)


def de_portal(tipo, cuenta, crear=True):
    """El participante de una cuenta de portal (`tipo`: portales.ESTUDIANTE o portales.TUTOR)."""
    if tipo == portales.ESTUDIANTE:
        return _obtener('alumno', cuenta, Participante.ESTUDIANTE, crear)
    return _obtener('tutor', cuenta, Participante.TUTOR, crear)


def de_clave(clave):
    """La cuenta de una clave («u:7», «a:12», «t:3») como participante (lo crea si hace falta), o None."""
    tipo, _, pk = (clave or '').partition(':')
    if not pk.isdigit():
        return None
    if tipo == 'u':
        usuario = get_user_model().objects.filter(pk=pk).first()
        return de_usuario(usuario) if usuario else None
    if tipo == 'a':
        alumno = Alumno.objects.filter(pk=pk).first()
        return de_portal(portales.ESTUDIANTE, alumno) if alumno else None
    if tipo == 't':
        tutor = Tutor.objects.filter(pk=pk).first()
        return de_portal(portales.TUTOR, tutor) if tutor else None
    return None


def activo(participante):
    """Si la cuenta puede usar la mensajería ahora (si no, no recibe mensajes nuevos)."""
    if participante.tipo == Participante.SISTEMA:
        return usa_mensajeria(participante.usuario)
    tipo = portales.ESTUDIANTE if participante.tipo == Participante.ESTUDIANTE else portales.TUTOR
    return not portales.motivo_sin_acceso(tipo, participante.cuenta)


# ---------------------------------------------------------------------------
# Quién con quién
# ---------------------------------------------------------------------------
def _grupos_actuales(alumnos):
    ciclo = ciclo_actual()
    if ciclo is None:
        return Inscripcion.objects.none().values('grupo')
    return Inscripcion.objects.filter(alumno__in=alumnos, ciclo=ciclo, activa=True).values('grupo')


def _imparte_a(usuario, alumnos):
    """Si el usuario es docente de alguno de esos estudiantes (una materia en su grupo del ciclo actual)."""
    ciclo = ciclo_actual()
    return ciclo is not None and MateriaGrado.objects.filter(
        profesor__usuario=usuario, ciclo=ciclo, activa=True, grupo__in=_grupos_actuales(alumnos),
    ).exists()


def _alcance_permite(usuario, alumnos):
    from Prefectura.alcance import alcance_de
    alcance = alcance_de(usuario)
    return alcance.total or alcance.alumnos(Alumno.objects.filter(pk__in=[a.pk for a in alumnos])).exists()


def _alumnos_de(participante):
    if participante.tipo == Participante.ESTUDIANTE:
        return [participante.alumno]
    return list(Alumno.objects.filter(tutores_relacionados__tutor=participante.tutor, tutores_relacionados__activo=True, estatus='ACTIVO'))


def relacion_permitida(uno, otro):
    """Si estas dos cuentas pueden conversar (es simétrica). No mira si están activas: eso es `pueden_conversar`."""
    if uno.pk is not None and uno.pk == otro.pk:
        return False
    if uno.tipo != Participante.SISTEMA:
        uno, otro = otro, uno
    if uno.tipo != Participante.SISTEMA:
        return False   # entre estudiantes, entre tutores o entre un estudiante y un tutor, nunca
    if otro.tipo == Participante.SISTEMA:
        return True
    usuario, alumnos = uno.usuario, _alumnos_de(otro)
    if not alumnos:
        return False
    if usuario.has_perm(FAMILIAS) and _alcance_permite(usuario, alumnos):
        return True
    return usuario.has_perm(USAR) and _imparte_a(usuario, alumnos)


def pueden_conversar(uno, otro):
    return activo(uno) and activo(otro) and relacion_permitida(uno, otro)


# ---------------------------------------------------------------------------
# Búsqueda de destinatarios
# ---------------------------------------------------------------------------
@dataclass
class Contacto:
    clave: str
    nombre: str
    detalle: str
    tipo: str
    iniciales: str

    def como_dict(self):
        return {'clave': self.clave, 'nombre': self.nombre, 'detalle': self.detalle, 'tipo': self.tipo, 'iniciales': self.iniciales}


def _palabras(consulta, texto, campos):
    for palabra in (texto or '').split():
        condicion = Q()
        for campo in campos:
            condicion |= Q(**{f'{campo}__icontains': palabra})
        consulta = consulta.filter(condicion)
    return consulta


def _usuarios_con(*permisos):
    condicion = Q(is_superuser=True)
    for permiso in permisos:
        app, codigo = permiso.split('.')
        condicion |= Q(groups__permissions__codename=codigo, groups__permissions__content_type__app_label=app)
        condicion |= Q(user_permissions__codename=codigo, user_permissions__content_type__app_label=app)
    return get_user_model().objects.filter(condicion, is_active=True).distinct()


def _rol_de(usuario):
    from Usuarios.seguridad import rol_de
    rol = rol_de(usuario)
    return rol.nombre if rol else 'Usuario del sistema'


def _alumnos_activos():
    return Alumno.objects.filter(estatus='ACTIVO', acceso_portal=True)


def _tutores_activos():
    return Tutor.objects.filter(estatus='ACTIVO', acceso_portal=True)


def contactos(participante, texto='', limite=25):
    """Las cuentas a las que puede escribir (con `texto`, las que coinciden), sin la propia."""
    resultado = []
    usuarios = get_user_model().objects.none()
    alumnos, tutores = Alumno.objects.none(), Tutor.objects.none()
    ciclo = ciclo_actual()
    if participante.tipo == Participante.SISTEMA:
        usuario = participante.usuario
        usuarios = _usuarios_con(USAR, FAMILIAS).exclude(pk=usuario.pk)
        if usuario.has_perm(FAMILIAS):
            from Prefectura.alcance import alcance_de
            alcance = alcance_de(usuario)
            alumnos = alcance.alumnos(_alumnos_activos())
            tutores = _tutores_activos().filter(Exists(TutorAlumno.objects.filter(
                tutor=OuterRef('pk'), activo=True, alumno__in=alcance.alumnos(Alumno.objects.filter(estatus='ACTIVO')))))
        elif usuario.has_perm(USAR) and ciclo is not None:
            grupos = MateriaGrado.objects.filter(profesor__usuario=usuario, ciclo=ciclo, activa=True).values('grupo')
            suyos = Inscripcion.objects.filter(ciclo=ciclo, activa=True, grupo__in=grupos).values('alumno')
            alumnos = _alumnos_activos().filter(pk__in=suyos)
            tutores = _tutores_activos().filter(Exists(TutorAlumno.objects.filter(tutor=OuterRef('pk'), activo=True, alumno__in=suyos)))
    else:
        propios = _alumnos_de(participante)
        if propios and ciclo is not None:
            docentes = MateriaGrado.objects.filter(ciclo=ciclo, activa=True, grupo__in=_grupos_actuales(propios)).values('profesor__usuario')
            usuarios = _usuarios_con(USAR, FAMILIAS).filter(pk__in=docentes)
        if propios:
            # Quien atiende a las familias (prefectura, solo si son de su alcance)
            atienden = [u for u in _usuarios_con(FAMILIAS) if _alcance_permite(u, propios)]
            usuarios = get_user_model().objects.filter(Q(pk__in=usuarios.values('pk')) | Q(pk__in=[u.pk for u in atienden]), is_active=True)

    usuarios = _palabras(usuarios, texto, ('first_name', 'last_name', 'username'))
    for usuario in usuarios.order_by('first_name', 'last_name', 'username')[:limite]:
        nombre = usuario.get_full_name() or usuario.get_username()
        iniciales = ''.join(p[0] for p in nombre.split()[:2]).upper()
        resultado.append(Contacto(f'u:{usuario.pk}', nombre, _rol_de(usuario), Participante.SISTEMA, iniciales))
    if texto:   # estudiantes y tutores solo al buscar: pueden ser muchos
        alumnos = _palabras(alumnos, texto, ('nombre', 'apellido_paterno', 'apellido_materno', 'referencia'))
        for alumno in alumnos.order_by('apellido_paterno', 'apellido_materno', 'nombre')[:limite]:
            resultado.append(Contacto(f'a:{alumno.pk}', str(alumno), f'Estudiante · {alumno.referencia}', Participante.ESTUDIANTE, alumno.iniciales))
        tutores = _palabras(tutores, texto, ('nombre', 'apellido_paterno', 'apellido_materno', 'usuario'))
        for tutor in tutores.order_by('apellido_paterno', 'apellido_materno', 'nombre')[:limite]:
            resultado.append(Contacto(f't:{tutor.pk}', str(tutor), 'Tutor', Participante.TUTOR, tutor.iniciales))
    return resultado[:limite]


# ---------------------------------------------------------------------------
# Conversaciones y mensajes
# ---------------------------------------------------------------------------
class MensajeRechazado(Exception):
    pass


def conversacion_con(origen, destino):
    """La conversación individual entre dos cuentas (la crea si no existe). MensajeRechazado si no pueden conversar."""
    if not pueden_conversar(origen, destino):
        raise MensajeRechazado('No puedes escribirle a esa persona.')
    clave = Conversacion.clave_de(origen, destino)
    conversacion = Conversacion.objects.filter(clave=clave).first()
    if conversacion is None:
        try:
            with transaction.atomic():
                conversacion = Conversacion.objects.create(clave=clave)
                Miembro.objects.bulk_create([Miembro(conversacion=conversacion, participante=p) for p in (origen, destino)])
        except IntegrityError:
            conversacion = Conversacion.objects.get(clave=clave)
    return conversacion


def miembro_de(conversacion, participante):
    return Miembro.objects.filter(conversacion=conversacion, participante=participante).first()


def el_otro(conversacion, participante):
    return Participante.objects.filter(membresias__conversacion=conversacion).exclude(pk=participante.pk).select_related(
        'usuario', 'alumno', 'tutor').first()


def puede_escribir_en(conversacion, participante):
    otro = el_otro(conversacion, participante)
    return otro is not None and pueden_conversar(participante, otro)


def _pendientes(conversacion, autor):
    """Lo que esa persona subió a esta conversación y todavía no envió."""
    return ImagenMensaje.objects.filter(conversacion=conversacion, autor=autor, mensaje__isnull=True)


def preparar_contenido(conversacion, autor, texto, html='', documentos=()):
    """(texto plano, html limpio, ids de imágenes, ids de documentos, sin_texto) de lo que se quiere enviar. Con `html`
    (el editor con formato), el texto sale de él y el HTML se limpia en el servidor: solo quedan las imágenes que esa
    persona subió a esta conversación y todavía no envió. Sin formato real, se guarda solo el texto. Los `documentos`
    (ids) valen si son PDF que esa persona subió aquí y no ha enviado. Sin nada escrito pero con documentos, el texto es
    su resumen («📎 circular.pdf»). MensajeRechazado si queda vacío (solo etiquetas de formato) o si es demasiado largo."""
    imagenes = []
    ids = [int(pk) for pk in documentos if str(pk).isdigit()]
    adjuntos = list(_pendientes(conversacion, autor).filter(pk__in=ids, tipo=ImagenMensaje.DOCUMENTO).order_by('pk')) if ids else []
    if len(adjuntos) > ImagenMensaje.DOCUMENTOS_POR_MENSAJE:
        raise MensajeRechazado(f'Se pueden adjuntar hasta {ImagenMensaje.DOCUMENTOS_POR_MENSAJE} documentos por mensaje.')
    if html and html.strip():
        if len(html) > Mensaje.MAXIMO_HTML * 3:
            raise MensajeRechazado('El mensaje es demasiado largo.')
        validas = set(_pendientes(conversacion, autor).filter(tipo__startswith='image/').values_list('pk', flat=True))
        html, imagenes = enriquecido.limpiar(html, imagenes_validas=validas)
        if enriquecido.tiene_contenido(html):
            texto = enriquecido.texto_plano(html)
            if enriquecido.es_texto_simple(html):
                html = ''
        else:
            html, texto = '', ''
        if len(html) > Mensaje.MAXIMO_HTML:
            raise MensajeRechazado('El mensaje tiene demasiado contenido o formato. Divídelo en varios mensajes.')
    else:
        html, texto = '', (texto or '').strip()
    sin_texto = not texto
    if sin_texto:
        if not adjuntos:
            raise MensajeRechazado('Escribe un mensaje.')
        texto = '\n'.join(f'📎 {documento.nombre_original}' for documento in adjuntos)
    if len(texto) > Mensaje.MAXIMO:
        raise MensajeRechazado(f'El mensaje es muy largo (máximo {Mensaje.MAXIMO} caracteres).')
    return texto, html, imagenes, [documento.pk for documento in adjuntos], sin_texto


def enviar(conversacion, autor, texto, html='', documentos=()):
    texto, html, imagenes, documentos, sin_texto = preparar_contenido(conversacion, autor, texto, html, documentos)
    if not puede_escribir_en(conversacion, autor):
        raise MensajeRechazado('Ya no puedes escribir en esta conversación.')
    from . import tiempo_real
    with transaction.atomic():
        mensaje = Mensaje.objects.create(conversacion=conversacion, autor=autor, texto=texto, html=html, sin_texto=sin_texto)
        if imagenes or documentos:
            _pendientes(conversacion, autor).filter(pk__in=[*imagenes, *documentos]).update(mensaje=mensaje)
        Conversacion.objects.filter(pk=conversacion.pk).update(actualizada=mensaje.creado, ultimo_mensaje=mensaje)
        ahora = timezone.now()
        Miembro.objects.filter(conversacion=conversacion, participante=autor).update(ultimo_leido=mensaje.pk, leido_en=ahora)
        # Quien responde ya leyó lo anterior: la otra persona lo ve como «Leído»
        leidos = Mensaje.objects.filter(conversacion=conversacion, pk__lt=mensaje.pk, leido_en__isnull=True).exclude(autor=autor).update(leido_en=ahora)
        transaction.on_commit(lambda: tiempo_real.avisar_mensaje(mensaje))
        if leidos:
            transaction.on_commit(lambda: tiempo_real.avisar_lectura(conversacion, autor, mensaje.pk, ahora))
    return mensaje


def html_visible(mensaje, participante):
    """El HTML del mensaje listo para mostrarse a `participante` (con las direcciones de sus imágenes según su espacio:
    el sistema o su portal); '' si el mensaje no tiene formato."""
    if not mensaje.html:
        return ''
    espacio = ESPACIO[participante.tipo]
    return enriquecido.presentar(mensaje.html, lambda pk: reverse(f'{espacio}:imagen', args=[pk]))


def marcar_leida(conversacion, participante):
    """Marca como leído todo lo que hay en la conversación (y la hora en cada mensaje de la otra persona que no se había
    leído). Devuelve True si había algo sin leer."""
    ultimo = conversacion.mensajes.order_by('-pk').values_list('pk', flat=True).first() or 0
    ahora = timezone.now()
    cambiados = Miembro.objects.filter(conversacion=conversacion, participante=participante, ultimo_leido__lt=ultimo).update(
        ultimo_leido=ultimo, leido_en=ahora)
    if cambiados:
        Mensaje.objects.filter(conversacion=conversacion, pk__lte=ultimo, leido_en__isnull=True).exclude(autor=participante).update(leido_en=ahora)
        from . import tiempo_real
        transaction.on_commit(lambda: tiempo_real.avisar_lectura(conversacion, participante, ultimo, ahora))
    return bool(cambiados)


def texto_de_lectura(momento):
    """«Leído a las 10:42», «Leído ayer a las 10:42» o «Leído el 18 de octubre a las 10:42» («Leído» sin la hora)."""
    if momento is None:
        return 'Leído'
    momento, hoy = timezone.localtime(momento), timezone.localdate()
    hora = momento.strftime('%H:%M')
    if momento.date() == hoy:
        return f'Leído a las {hora}'
    if momento.date() == hoy - timedelta(days=1):
        return f'Leído ayer a las {hora}'
    formato = 'j \\d\\e F' if momento.year == hoy.year else 'j \\d\\e F \\d\\e Y'
    return f'Leído el {date_format(momento, formato).lower()} a las {hora}'


def con_documentos(mensajes, url_de):
    """Pone en cada mensaje `documentos`: sus PDF adjuntos (con `url`, la dirección para quien mira). Una sola consulta."""
    mensajes = list(mensajes)
    por_mensaje = {}
    for documento in ImagenMensaje.objects.filter(mensaje__in=[m.pk for m in mensajes], tipo=ImagenMensaje.DOCUMENTO).order_by('pk'):
        documento.url = url_de(documento.pk)
        por_mensaje.setdefault(documento.mensaje_id, []).append(documento)
    for mensaje in mensajes:
        mensaje.documentos = por_mensaje.get(mensaje.pk, [])
    return mensajes


def leido_por_el_otro(conversacion, participante):
    """Hasta qué mensaje leyó la otra persona (para el «leído» de los mensajes propios)."""
    return Miembro.objects.filter(conversacion=conversacion).exclude(participante=participante).values_list('ultimo_leido', flat=True).first() or 0


def _sin_leer(participante):
    """Los mensajes de otros que la persona no ha leído, por conversación."""
    suyo_sin_leer = Miembro.objects.filter(conversacion=OuterRef('conversacion'), participante=participante, ultimo_leido__lt=OuterRef('pk'))
    return Mensaje.objects.filter(Exists(suyo_sin_leer)).exclude(autor=participante)


def no_leidos(participante):
    if participante is None:
        return 0
    return _sin_leer(participante).count()


def cursor_de(conversacion):
    """Dónde sigue la bandeja después de esta conversación («<microsegundos>-<id>»: su fecha y su id)."""
    return f'{int(conversacion.actualizada.timestamp() * 1_000_000)}-{conversacion.pk}'


def _desde_cursor(cursor):
    """(fecha, id) de un cursor de la bandeja, o None si no es válido."""
    momento, _, pk = (cursor or '').partition('-')
    if not (momento.isdigit() and pk.isdigit()):
        return None
    return datetime(1970, 1, 1, tzinfo=dt_timezone.utc) + timedelta(microseconds=int(momento)), int(pk)


def bandeja(participante, limite=60, despues=None):
    """Las conversaciones de la persona, de la más reciente a la más antigua, con la otra persona, el último mensaje y
    cuántos mensajes no ha leído. Con `despues` (un cursor de `cursor_de`), las que siguen a esa."""
    pendientes = dict(_sin_leer(participante).values('conversacion').annotate(n=Count('pk')).values_list('conversacion', 'n'))
    consulta = Conversacion.objects.filter(miembros__participante=participante, ultimo_mensaje__isnull=False)
    if (desde := _desde_cursor(despues)) is not None:
        consulta = consulta.filter(Q(actualizada__lt=desde[0]) | Q(actualizada=desde[0], pk__lt=desde[1]))
    conversaciones = list(consulta.select_related('ultimo_mensaje__autor').order_by('-actualizada', '-pk')[:limite])
    otros = {
        m.conversacion_id: m.participante for m in
        Miembro.objects.filter(conversacion__in=conversaciones).exclude(participante=participante).select_related(
            'participante__usuario', 'participante__alumno', 'participante__tutor')
    }
    for conversacion in conversaciones:
        conversacion.otro = otros.get(conversacion.pk)
        conversacion.no_leidos = pendientes.get(conversacion.pk, 0)
        conversacion.mio = conversacion.ultimo_mensaje.autor_id == participante.pk
    return [c for c in conversaciones if c.otro is not None]


POR_PAGINA_BANDEJA = 60


def pagina_de_bandeja(participante, despues=None, limite=None):
    """(conversaciones, cursor de las siguientes o None si ya no hay más)."""
    limite = limite or POR_PAGINA_BANDEJA
    conversaciones = bandeja(participante, limite=limite + 1, despues=despues)
    if len(conversaciones) > limite:
        conversaciones = conversaciones[:limite]
        return conversaciones, cursor_de(conversaciones[-1])
    return conversaciones, None


def vista_previa(texto):
    texto = ' '.join(texto.split())
    return texto if len(texto) <= VISTA_PREVIA else texto[:VISTA_PREVIA - 1].rstrip() + '…'


def avisos(participante, limite=6):
    """Las conversaciones con mensajes sin leer (las de la campana de notificaciones)."""
    if participante is None:
        return []
    return [c for c in bandeja(participante, limite=40) if c.no_leidos][:limite]


def historial(conversacion, antes=None, cantidad=50):
    """(mensajes en orden, hay_anteriores): los últimos `cantidad`, o los anteriores al id `antes`."""
    consulta = conversacion.mensajes.select_related('autor')
    if antes:
        consulta = consulta.filter(pk__lt=antes)
    mensajes = list(consulta.order_by('-pk')[:cantidad + 1])
    hay_anteriores = len(mensajes) > cantidad
    return list(reversed(mensajes[:cantidad])), hay_anteriores


CON_CUENTA = ('autor__usuario', 'autor__alumno', 'autor__tutor')


def ventana(conversacion, alrededor, cantidad=50):
    """(mensajes en orden, hay_anteriores, hay_posteriores): los que están antes y después del mensaje `alrededor` (un
    id), para abrir la conversación en un mensaje encontrado."""
    base = conversacion.mensajes.select_related(*CON_CUENTA)
    mitad = cantidad // 2
    previos = list(base.filter(pk__lt=alrededor).order_by('-pk')[:mitad + 1])
    siguientes = list(base.filter(pk__gte=alrededor).order_by('pk')[:mitad + 1])
    return list(reversed(previos[:mitad])) + siguientes[:mitad], len(previos) > mitad, len(siguientes) > mitad


# ---------------------------------------------------------------------------
# Buscar en las conversaciones
# ---------------------------------------------------------------------------
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


def buscar_mensajes(participante, texto, limite=20):
    """Los mensajes de las conversaciones de la persona que tienen cada palabra (en el texto o en el nombre de un
    documento adjunto), del más reciente al más antiguo, con `otro` (con quién es la conversación) y `fragmento`."""
    palabras = (texto or '').split()
    if not palabras or len(texto.strip()) < 2:
        return []
    consulta = Mensaje.objects.filter(conversacion__miembros__participante=participante)
    for palabra in palabras:
        consulta = consulta.filter(Q(texto__icontains=palabra) | Q(imagenes__nombre_original__icontains=palabra))
    mensajes = list(consulta.distinct().select_related('autor').order_by('-pk')[:limite])
    otros = {
        m.conversacion_id: m.participante for m in
        Miembro.objects.filter(conversacion__in={m.conversacion_id for m in mensajes}).exclude(participante=participante)
        .select_related('participante__usuario', 'participante__alumno', 'participante__tutor')
    }
    for mensaje in mensajes:
        mensaje.otro = otros.get(mensaje.conversacion_id)
        mensaje.mio = mensaje.autor_id == participante.pk
        mensaje.fragmento = resaltar(mensaje.texto, texto, largo=140)
    return [m for m in mensajes if m.otro is not None]
