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
from django.db.models import Count, Exists, OuterRef, Q, Value
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from Alumnos.academico import ciclo_actual
from Alumnos.models import Alumno, Inscripcion, MateriaGrado, Tutor, TutorAlumno
from CISAHUAYO import portales
from CISAHUAYO.sin_acentos import quitar_acentos

from . import enriquecido
from .models import ConfiguracionMensajes, Conversacion, ImagenMensaje, Mensaje, Miembro, Participante, ReporteMensaje

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


def _desde_html(html, imagenes_validas):
    """(texto plano, html limpio, ids de imágenes) de lo que manda el editor con formato. Sin formato real, el html queda
    vacío (basta el texto); sin nada escrito, los dos. MensajeRechazado si es demasiado largo."""
    if len(html) > Mensaje.MAXIMO_HTML * 3:
        raise MensajeRechazado('El mensaje es demasiado largo.')
    html, imagenes = enriquecido.limpiar(html, imagenes_validas=imagenes_validas)
    if enriquecido.tiene_contenido(html):
        texto = enriquecido.texto_plano(html)
        if enriquecido.es_texto_simple(html):
            html = ''
    else:
        html, texto = '', ''
    if len(html) > Mensaje.MAXIMO_HTML:
        raise MensajeRechazado('El mensaje tiene demasiado contenido o formato. Divídelo en varios mensajes.')
    return texto, html, imagenes


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
        validas = set(_pendientes(conversacion, autor).filter(tipo__startswith='image/').values_list('pk', flat=True))
        texto, html, imagenes = _desde_html(html, validas)
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


# Mensajes seguidos que una persona puede mandar en una conversación en un minuto (que nadie llene de mensajes a otra)
POR_MINUTO = 10


def enviar(conversacion, autor, texto, html='', documentos=(), responde_a=None):
    texto, html, imagenes, documentos, sin_texto = preparar_contenido(conversacion, autor, texto, html, documentos)
    if not puede_escribir_en(conversacion, autor):
        raise MensajeRechazado('Ya no puedes escribir en esta conversación.')
    recientes = conversacion.mensajes.filter(autor=autor, creado__gte=timezone.now() - timedelta(minutes=1)).count()
    if recientes >= POR_MINUTO:
        raise MensajeRechazado('Enviaste muchos mensajes seguidos. Espera un minuto antes de enviar otro.')
    # La cita solo vale con un mensaje de la misma conversación (si no, se envía sin cita)
    citado = conversacion.mensajes.filter(pk=responde_a).first() if str(responde_a or '').isdigit() else None
    from . import push, tiempo_real
    with transaction.atomic():
        mensaje = Mensaje.objects.create(conversacion=conversacion, autor=autor, texto=texto, html=html, sin_texto=sin_texto,
                                         responde_a=citado)
        if imagenes or documentos:
            _pendientes(conversacion, autor).filter(pk__in=[*imagenes, *documentos]).update(mensaje=mensaje)
        Conversacion.objects.filter(pk=conversacion.pk).update(actualizada=mensaje.creado, ultimo_mensaje=mensaje)
        ahora = timezone.now()
        Miembro.objects.filter(conversacion=conversacion, participante=autor).update(ultimo_leido=mensaje.pk, leido_en=ahora, marcada_sin_leer=False)
        # Quien responde ya leyó lo anterior: la otra persona lo ve como «Leído»
        leidos = Mensaje.objects.filter(conversacion=conversacion, pk__lt=mensaje.pk, leido_en__isnull=True).exclude(autor=autor).update(leido_en=ahora)
        transaction.on_commit(lambda: tiempo_real.avisar_mensaje(mensaje))
        transaction.on_commit(lambda: push.avisar_mensaje(mensaje))   # también con la página cerrada
        if leidos:
            transaction.on_commit(lambda: tiempo_real.avisar_lectura(conversacion, autor, mensaje.pk, ahora))
    return mensaje


# ---------------------------------------------------------------------------
# Corregir un mensaje propio (2026-10-23)
# ---------------------------------------------------------------------------
MINUTOS_PARA_EDITAR = 2


def se_puede_editar(mensaje, participante, ahora=None):
    """Su autor, en los primeros minutos, con texto escrito y sin imágenes dentro (los documentos se conservan)."""
    ahora = ahora or timezone.now()
    return (
        mensaje.autor_id == participante.pk and not mensaje.sin_texto
        and ahora - mensaje.creado <= timedelta(minutes=MINUTOS_PARA_EDITAR)
        and 'data-imagen' not in (mensaje.html or '')
    )


def editar(mensaje, participante, texto, html=''):
    """Cambia el texto del mensaje y lo marca «editado». Un mensaje con formato se corrige con su formato (`html`, que se
    limpia como al enviar); sin `html`, queda como texto. MensajeRechazado si ya no se puede o si queda vacío o
    demasiado largo."""
    if not puede_escribir_en(mensaje.conversacion, participante):
        raise MensajeRechazado('Ya no puedes escribir en esta conversación.')
    if not se_puede_editar(mensaje, participante):
        raise MensajeRechazado(f'Solo puedes corregir tus mensajes de texto en los primeros {MINUTOS_PARA_EDITAR} minutos.')
    if html and html.strip():
        texto, html, _ = _desde_html(html, imagenes_validas=set())   # se corrigen los que no tienen imágenes
    else:
        texto, html = (texto or '').strip(), ''
    if not texto:
        raise MensajeRechazado('Escribe un mensaje.')
    if len(texto) > Mensaje.MAXIMO:
        raise MensajeRechazado(f'El mensaje es muy largo (máximo {Mensaje.MAXIMO} caracteres).')
    from . import tiempo_real
    with transaction.atomic():
        mensaje.texto, mensaje.html, mensaje.editado = texto, html, timezone.now()
        mensaje.save(update_fields=['texto', 'html', 'editado'])
        transaction.on_commit(lambda: tiempo_real.avisar_edicion(mensaje))
    return mensaje


# ---------------------------------------------------------------------------
# Horario de atención (2026-10-27)
# ---------------------------------------------------------------------------
def _hora(valor):
    return f'{valor.hour}:{valor.minute:02d}'


def aviso_fuera_de_horario(participante, otro, momento=None):
    """El aviso para un estudiante o un tutor que le escribe al personal fuera del horario de atención (Ajustes ›
    Mensajes): de noche, en fin de semana o en un día sin clases de todo el colegio. '' en horario, con el aviso apagado
    o entre otras cuentas. No impide escribir."""
    if participante.tipo == Participante.SISTEMA or otro is None or otro.tipo != Participante.SISTEMA:
        return ''
    configuracion = ConfiguracionMensajes.actual()
    if not configuracion.avisar_fuera_de_horario:
        return ''
    from Alumnos.asistencias import motivo_sin_clases
    momento = timezone.localtime(momento)
    if motivo_sin_clases(momento.date()) is None and configuracion.hora_inicio <= momento.time() < configuracion.hora_fin:
        return ''
    return (f'Estás escribiendo fuera del horario de atención del colegio (de lunes a viernes, de '
            f'{_hora(configuracion.hora_inicio)} a {_hora(configuracion.hora_fin)}, en días de clases). Tu mensaje se '
            f'entrega al momento, pero la respuesta puede llegar hasta el siguiente día de clases.')


# ---------------------------------------------------------------------------
# Reportar un mensaje inapropiado (2026-10-27)
# ---------------------------------------------------------------------------
def reportar(mensaje, participante, motivo=''):
    """Quien recibió el mensaje lo reporta al administrador (Mensajes/moderacion.py), con un motivo opcional. Una vez por
    persona y mensaje: si lo vuelve a reportar, se actualiza el motivo. Quien lo escribió no se entera. También en una
    conversación que ya no admite mensajes nuevos. MensajeRechazado si es un mensaje propio."""
    if mensaje.autor_id == participante.pk:
        raise MensajeRechazado('Solo puedes reportar los mensajes que recibiste.')
    motivo = ' '.join((motivo or '').split())[:ReporteMensaje.MOTIVO_MAXIMO]
    reporte, _ = ReporteMensaje.objects.update_or_create(mensaje=mensaje, participante=participante, defaults={'motivo': motivo})
    return reporte


def reportados_por(participante, mensajes):
    """Los ids de esos mensajes que la persona ya reportó (y que siguen esperando revisión)."""
    return set(ReporteMensaje.objects.filter(participante=participante, mensaje__in=[m.pk for m in mensajes]).values_list('mensaje_id', flat=True))


def cita_de(mensaje):
    """Lo que se muestra del mensaje citado: {id, autor, texto} o None."""
    citado = mensaje.responde_a
    if citado is None:
        return None
    return {'id': citado.pk, 'autor': citado.autor.nombre, 'texto': vista_previa(citado.texto)}


# ---------------------------------------------------------------------------
# Quién es cada persona (bajo su nombre en la lista y en la conversación)
# ---------------------------------------------------------------------------
def familias_de(tutores):
    """{tutor_id: «Tutor de Ana López (3.º B) y Luis López (1.º A)»} con sus estudiantes de vínculo activo y su grupo del
    ciclo actual; en una sola consulta."""
    ids = [t.pk for t in tutores]
    if not ids:
        return {}
    ciclo = ciclo_actual()
    estudiantes = {}
    for vinculo in (TutorAlumno.objects.filter(tutor_id__in=ids, alumno__estatus='ACTIVO').select_related('alumno')
                    .order_by('-tutor_principal', 'alumno__nombre')):
        estudiantes.setdefault(vinculo.tutor_id, []).append(vinculo.alumno)
    grupos = {}
    if ciclo is not None:
        for inscripcion in (Inscripcion.objects.filter(activa=True, ciclo=ciclo, alumno__in=[a for lista in estudiantes.values() for a in lista])
                            .select_related('grupo__grado', 'grupo__nombre')):
            grupos[inscripcion.alumno_id] = inscripcion.grupo
    textos = {}
    for tutor_id, lista in estudiantes.items():
        nombres = [f'{a.nombre_completo} ({grupos[a.pk]})' if a.pk in grupos else a.nombre_completo for a in lista[:3]]
        if len(lista) > 3:
            nombres[-1] += f' y {len(lista) - 3} más'
        textos[tutor_id] = 'Tutor de ' + (', '.join(nombres[:-1]) + ' y ' + nombres[-1] if len(nombres) > 1 else nombres[0])
    return textos


def html_visible(mensaje, participante):
    """El HTML del mensaje listo para mostrarse a `participante` (con las direcciones de sus imágenes según su espacio:
    el sistema o su portal); '' si el mensaje no tiene formato."""
    if not mensaje.html:
        return ''
    espacio = ESPACIO[participante.tipo]
    return enriquecido.presentar(mensaje.html, lambda pk: reverse(f'{espacio}:imagen', args=[pk]))


def marcar_leida(conversacion, participante, hasta=None):
    """Marca como leído todo lo que hay en la conversación (y la hora en cada mensaje de la otra persona que no se había
    leído); con `hasta` (un id), solo hasta ese mensaje: lo que vino después no se ha visto. Si la había dejado «no
    leída», deja de estarlo. Devuelve True si había algo sin leer."""
    mensajes = conversacion.mensajes.filter(pk__lte=hasta) if hasta else conversacion.mensajes
    ultimo = mensajes.order_by('-pk').values_list('pk', flat=True).first() or 0
    ahora = timezone.now()
    suyo = Miembro.objects.filter(conversacion=conversacion, participante=participante)
    desmarcada = suyo.filter(marcada_sin_leer=True).update(marcada_sin_leer=False)
    cambiados = suyo.filter(ultimo_leido__lt=ultimo).update(ultimo_leido=ultimo, leido_en=ahora)
    from . import tiempo_real
    if cambiados:
        Mensaje.objects.filter(conversacion=conversacion, pk__lte=ultimo, leido_en__isnull=True).exclude(autor=participante).update(leido_en=ahora)
        transaction.on_commit(lambda: tiempo_real.avisar_lectura(conversacion, participante, ultimo, ahora))
    elif desmarcada:   # solo la marca: la otra persona no tiene nada que saber; sus otras pestañas, sí
        transaction.on_commit(lambda: tiempo_real.avisar_resumen(participante, conversacion.pk))
    return bool(cambiados or desmarcada)


def marcar_no_leida(conversacion, participante):
    """La persona deja la conversación «no leída» para acordarse de atenderla, como en el correo (pedido del
    2026-10-27): cuenta como pendiente en su lista y en su campana hasta que la vuelve a abrir o escribe en ella. Es solo
    suya: la otra persona sigue viendo sus mensajes como leídos. MensajeRechazado si la conversación no tiene mensajes."""
    if not conversacion.mensajes.exists():
        raise MensajeRechazado('Esta conversación todavía no tiene mensajes.')
    Miembro.objects.filter(conversacion=conversacion, participante=participante).update(marcada_sin_leer=True)
    from . import tiempo_real
    transaction.on_commit(lambda: tiempo_real.avisar_resumen(participante, conversacion.pk))


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


def miembro_de_la_otra_persona(conversacion, participante):
    """El `Miembro` de la otra persona (hasta dónde leyó y cuándo), o None."""
    return Miembro.objects.filter(conversacion=conversacion).exclude(participante=participante).first()


def _sin_leer(participante):
    """Los mensajes de otros que la persona no ha leído, por conversación."""
    suyo_sin_leer = Miembro.objects.filter(conversacion=OuterRef('conversacion'), participante=participante, ultimo_leido__lt=OuterRef('pk'))
    return Mensaje.objects.filter(Exists(suyo_sin_leer)).exclude(autor=participante)


def no_leidos(participante):
    """Los mensajes sin leer, más uno por cada conversación que dejó «no leída» y no tiene ninguno."""
    if participante is None:
        return 0
    return sum(sin_leer_por_conversacion(participante).values())


def sin_leer_por_conversacion(participante):
    """{conversacion_id: mensajes sin leer} (solo las que tienen alguno; una que dejó «no leída» cuenta al menos uno):
    una sola consulta."""
    reales = _sin_leer(participante).order_by().values('conversacion').annotate(n=Count('pk')).values_list('conversacion', 'n')
    marcadas = Miembro.objects.filter(participante=participante, marcada_sin_leer=True).annotate(n=Value(1)).values_list('conversacion', 'n')
    pendientes = {}
    for conversacion, n in reales.union(marcadas, all=True).order_by():   # sin el orden de Mensaje (no está en la unión)
        pendientes[conversacion] = max(pendientes.get(conversacion, 0), n)
    return pendientes


def cursor_de(conversacion):
    """Dónde sigue la bandeja después de esta conversación («<microsegundos>-<id>»: su fecha y su id)."""
    return f'{int(conversacion.actualizada.timestamp() * 1_000_000)}-{conversacion.pk}'


def _desde_cursor(cursor):
    """(fecha, id) de un cursor de la bandeja, o None si no es válido."""
    momento, _, pk = (cursor or '').partition('-')
    if not (momento.isdigit() and pk.isdigit()):
        return None
    return datetime(1970, 1, 1, tzinfo=dt_timezone.utc) + timedelta(microseconds=int(momento)), int(pk)


def bandeja(participante, limite=60, despues=None, pendientes=None, solo_sin_leer=False, incluir=None):
    """Las conversaciones de la persona, de la más reciente a la más antigua, con la otra persona, el último mensaje y
    cuántos mensajes no ha leído. Con `despues` (un cursor de `cursor_de`), las que siguen a esa; con `solo_sin_leer`,
    solo las que tienen algo sin leer (`pendientes`: lo de `sin_leer_por_conversacion`, si ya se consultó) y la de id
    `incluir` (la que tiene abierta: al abrirla quedó leída, pero sigue en la lista)."""
    pendientes = sin_leer_por_conversacion(participante) if pendientes is None else pendientes
    consulta = Conversacion.objects.filter(miembros__participante=participante, ultimo_mensaje__isnull=False)
    if solo_sin_leer:
        consulta = consulta.filter(Q(pk__in=list(pendientes)) | Q(pk=incluir) if incluir else Q(pk__in=list(pendientes)))
    if (desde := _desde_cursor(despues)) is not None:
        consulta = consulta.filter(Q(actualizada__lt=desde[0]) | Q(actualizada=desde[0], pk__lt=desde[1]))
    conversaciones = list(consulta.select_related('ultimo_mensaje__autor').order_by('-actualizada', '-pk')[:limite])
    otros = {
        m.conversacion_id: m.participante for m in
        Miembro.objects.filter(conversacion__in=conversaciones).exclude(participante=participante).select_related(
            'participante__usuario', 'participante__alumno', 'participante__tutor')
    }
    familias = familias_de([p.tutor for p in otros.values() if p.tipo == Participante.TUTOR])
    for conversacion in conversaciones:
        conversacion.otro = otros.get(conversacion.pk)
        if conversacion.otro is not None and conversacion.otro.tipo == Participante.TUTOR:
            conversacion.otro.quien = familias.get(conversacion.otro.tutor_id, '')
        conversacion.no_leidos = pendientes.get(conversacion.pk, 0)
        conversacion.mio = conversacion.ultimo_mensaje.autor_id == participante.pk
    return [c for c in conversaciones if c.otro is not None]


POR_PAGINA_BANDEJA = 60


def pagina_de_bandeja(participante, despues=None, limite=None, solo_sin_leer=False, incluir=None):
    """(conversaciones, cursor de las siguientes o None si ya no hay más). Con `solo_sin_leer`, el filtro «Sin leer» de
    la bandeja (y `incluir`, la conversación abierta): ver `bandeja`."""
    limite = limite or POR_PAGINA_BANDEJA
    conversaciones = bandeja(participante, limite=limite + 1, despues=despues, solo_sin_leer=solo_sin_leer, incluir=incluir)
    if len(conversaciones) > limite:
        conversaciones = conversaciones[:limite]
        return conversaciones, cursor_de(conversaciones[-1])
    return conversaciones, None


def vista_previa(texto):
    texto = ' '.join(texto.split())
    return texto if len(texto) <= VISTA_PREVIA else texto[:VISTA_PREVIA - 1].rstrip() + '…'


def avisos(participante, limite=6, pendientes=None):
    """Las conversaciones con mensajes sin leer (las de la campana de notificaciones). Sin nada sin leer, no se arma
    ninguna conversación: la campana está en todas las páginas."""
    if participante is None:
        return []
    pendientes = sin_leer_por_conversacion(participante) if pendientes is None else pendientes
    if not pendientes:
        return []
    return bandeja(participante, limite=limite, pendientes=pendientes, solo_sin_leer=True)


def historial(conversacion, antes=None, cantidad=50):
    """(mensajes en orden, hay_anteriores): los últimos `cantidad`, o los anteriores al id `antes`."""
    consulta = conversacion.mensajes.select_related('autor', 'responde_a__autor__usuario', 'responde_a__autor__alumno', 'responde_a__autor__tutor')
    if antes:
        consulta = consulta.filter(pk__lt=antes)
    mensajes = list(consulta.order_by('-pk')[:cantidad + 1])
    hay_anteriores = len(mensajes) > cantidad
    return list(reversed(mensajes[:cantidad])), hay_anteriores


CON_CUENTA = ('autor__usuario', 'autor__alumno', 'autor__tutor')


def ventana(conversacion, alrededor, cantidad=50):
    """(mensajes en orden, hay_anteriores, hay_posteriores): los que están antes y después del mensaje `alrededor` (un
    id), para abrir la conversación en un mensaje encontrado."""
    base = conversacion.mensajes.select_related(*CON_CUENTA, 'responde_a__autor__usuario', 'responde_a__autor__alumno', 'responde_a__autor__tutor')
    mitad = cantidad // 2
    previos = list(base.filter(pk__lt=alrededor).order_by('-pk')[:mitad + 1])
    siguientes = list(base.filter(pk__gte=alrededor).order_by('pk')[:mitad + 1])
    return list(reversed(previos[:mitad])) + siguientes[:mitad], len(previos) > mitad, len(siguientes) > mitad


# ---------------------------------------------------------------------------
# Buscar en las conversaciones
# ---------------------------------------------------------------------------
def _plegado(texto):
    """(el texto sin acentos y en minúsculas, la posición en `texto` de cada carácter del plegado): para encontrar lo
    buscado igual que la base de datos (CISAHUAYO/sin_acentos.py) y resaltarlo en el texto original."""
    letras, origen = [], []
    for posicion, caracter in enumerate(texto):
        for letra in quitar_acentos(caracter):
            letras.append(letra)
            origen.append(posicion)
    return ''.join(letras), origen


def resaltar(texto, buscado='', largo=220):
    """El texto en una línea, recortado alrededor de la primera coincidencia, con las palabras buscadas en <mark> (todo
    lo demás, escapado). Como la búsqueda, no distingue acentos ni mayúsculas: «excursion» resalta «Excursión»."""
    texto = ' '.join((texto or '').split())
    palabras = [re.escape(p) for p in quitar_acentos(buscado or '').split()]
    coincidencias = []
    if palabras:
        plegado, origen = _plegado(texto)
        coincidencias = [(origen[c.start()], origen[c.end() - 1] + 1) for c in re.finditer('|'.join(palabras), plegado)]
    inicio = 0
    if coincidencias and coincidencias[0][0] > largo // 3:
        inicio = coincidencias[0][0] - largo // 4
    fin = inicio + largo
    partes, ultimo = [], inicio
    for desde, hasta in coincidencias:
        if desde < ultimo or desde >= fin:
            continue
        hasta = min(hasta, fin)
        partes.append(conditional_escape(texto[ultimo:desde]))
        partes.append(f'<mark>{conditional_escape(texto[desde:hasta])}</mark>')
        ultimo = hasta
    partes.append(conditional_escape(texto[ultimo:fin]))
    return mark_safe(('…' if inicio else '') + ''.join(partes) + ('…' if fin < len(texto) else ''))


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
