"""Las operaciones de los comunicados: enviar, leer, listar, dar seguimiento y eliminar.

- Enviar: lo valida todo en el servidor (alcance de quien envía, destinatarios, expiración posterior al envío) y lo
  guarda de una sola vez (comunicado, destinatarios y archivos). La `clave_envio` que trae el formulario hace que un
  doble clic o un reintento devuelvan el mismo comunicado en lugar de crear otro.
- Leer: la primera vez que el destinatario abre el detalle se guarda la fecha y hora; abrirlo otra vez no la cambia.
  Ver la tarjeta, recibir el aviso o que el autor o el administrador consulten el seguimiento no cuenta como lectura.
- Caducar: un comunicado con fecha de expiración ya cumplida deja de verse y de abrirse para sus destinatarios (aun
  con un enlace directo); se compara con la hora del servidor en cada consulta, sin depender de tareas programadas.
  El autor y el administrador conservan el histórico con sus estadísticas.
- Gestionar: el administrador, todos; los demás, solo los suyos (pertenecer al mismo nivel no deja ver los de otros).
"""
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from .alcance import ELIMINAR, RECIBIR, SEGUIMIENTO, SIN_NIVELES, FueraDeAlcance, alcance_de, es_administrador
from .models import Adjunto, Comunicado, Destinatario

PLURAL = {Destinatario.TUTOR: ('tutor', 'tutores'), Destinatario.ESTUDIANTE: ('estudiante', 'estudiantes'),
          Destinatario.PROFESOR: ('profesor', 'profesores')}
ORDEN_DE_TIPOS = (Destinatario.TUTOR, Destinatario.ESTUDIANTE, Destinatario.PROFESOR)


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
# Enviar
# ---------------------------------------------------------------------------
def enviar(autor, *, titulo, descripcion, urgente, expira, clave_envio, seleccion, archivos=(), ahora=None):
    """Guarda y publica el comunicado. Devuelve (comunicado, nuevo): `nuevo` es False si esa clave de envío ya se había
    usado (doble clic o reintento). `archivos`: [(archivo subido, tipo real)] ya validados. EnvioRechazado si no
    procede."""
    ahora = ahora or timezone.now()
    previo = Comunicado.objects.filter(clave_envio=clave_envio).first()
    if previo is not None:
        if previo.autor_id != autor.pk:
            raise EnvioRechazado('El formulario caducó. Vuelve a abrirlo para enviar el comunicado.')
        return previo, False

    alcance = alcance_de(autor)
    if not alcance.puede_enviar:
        raise EnvioRechazado(SIN_NIVELES)
    if expira is not None and expira <= ahora:
        raise EnvioRechazado('La fecha de expiración debe ser posterior al momento del envío.', 'expira')
    try:
        elegidos = alcance.validar(seleccion)
    except FueraDeAlcance:
        raise EnvioRechazado('Algunas de las personas elegidas están fuera de los niveles a los que puedes enviar. Vuelve a '
                             'elegir los destinatarios.', 'destinatarios') from None
    if not any(elegidos.values()):
        raise EnvioRechazado('Elige al menos un destinatario.', 'destinatarios')
    if len(archivos) > Comunicado.MAXIMO_ADJUNTOS:
        raise EnvioRechazado(f'Adjunta como máximo {Comunicado.MAXIMO_ADJUNTOS} archivos.', 'archivos')

    detalles = alcance.detalles(elegidos)
    campo = {Destinatario.ESTUDIANTE: 'alumno_id', Destinatario.TUTOR: 'tutor_id', Destinatario.PROFESOR: 'profesor_id'}
    try:
        with transaction.atomic():
            comunicado = Comunicado.objects.create(
                titulo=titulo, descripcion=descripcion, urgente=urgente, expira=expira, autor=autor,
                rol_autor=rol_visible(autor)[:80], creado=ahora, clave_envio=clave_envio,
            )
            Destinatario.objects.bulk_create([
                Destinatario(comunicado=comunicado, tipo=tipo, detalle=detalles[tipo].get(pk, '')[:250], **{campo[tipo]: pk})
                for tipo in ORDEN_DE_TIPOS for pk in sorted(elegidos[tipo])
            ])
            for orden, (archivo, tipo) in enumerate(archivos):
                Adjunto.objects.create(comunicado=comunicado, archivo=archivo, nombre_original=_nombre_de_archivo(archivo.name),
                                       tipo=tipo, tamano=archivo.size, orden=orden)
            from Usuarios.seguridad import ACCION_ALTA, registrar
            total = sum(len(ids) for ids in elegidos.values())
            registrar(autor, comunicado, ACCION_ALTA, f'Envió el comunicado a {total} destinatario{"s" if total != 1 else ""} '
                                                     f'({resumen_por_tipo({t: len(i) for t, i in elegidos.items()})}).')
            from . import tiempo_real
            transaction.on_commit(lambda: tiempo_real.avisar_comunicado(comunicado.pk))
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
# Quién lee
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Lector:
    """Una persona que recibe comunicados: un profesor (con su cuenta del sistema), un estudiante o un tutor (con su
    portal)."""
    tipo: str
    persona: object

    @property
    def campo(self):
        return {Destinatario.ESTUDIANTE: 'alumno', Destinatario.TUTOR: 'tutor', Destinatario.PROFESOR: 'profesor'}[self.tipo]

    def destinatarios(self, ahora=None):
        """Sus copias de los comunicados que puede ver: no eliminados ni caducados."""
        ahora = ahora or timezone.now()
        return Destinatario.objects.filter(**{self.campo: self.persona}, comunicado__eliminado=False).filter(
            Q(comunicado__expira__isnull=True) | Q(comunicado__expira__gt=ahora))

    def pendientes(self):
        """(sin leer, urgentes sin leer)"""
        conteo = self.destinatarios().filter(leido_en__isnull=True).aggregate(
            total=Count('pk'), urgentes=Count('pk', filter=Q(comunicado__urgente=True)))
        return conteo['total'] or 0, conteo['urgentes'] or 0


def lector_de_usuario(usuario):
    """Un profesor con permiso para consultar comunicados; cualquier otra cuenta del sistema no recibe."""
    from Usuarios.docentes import profesor_de
    if not (usuario and usuario.is_authenticated and usuario.is_active and usuario.has_perm(RECIBIR)):
        return None
    profesor = profesor_de(usuario)
    return Lector(Destinatario.PROFESOR, profesor) if profesor is not None else None


def lector_de_portal(tipo, cuenta):
    from CISAHUAYO import portales
    return Lector(Destinatario.ESTUDIANTE if tipo == portales.ESTUDIANTE else Destinatario.TUTOR, cuenta)


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


def recibidos(lector, estado='todos'):
    """Sus copias, con los urgentes sin leer primero y luego del más reciente al más antiguo."""
    adjuntos = Adjunto.objects.filter(comunicado=OuterRef('comunicado')).order_by().values('comunicado').annotate(n=Count('pk')).values('n')
    consulta = lector.destinatarios().select_related('comunicado__autor').annotate(
        adjuntos=Coalesce(Subquery(adjuntos, output_field=IntegerField()), 0),
        prioridad=Case(When(leido_en__isnull=True, comunicado__urgente=True, then=Value(0)), default=Value(1), output_field=IntegerField()),
    )
    if estado == 'pendientes':
        consulta = consulta.filter(leido_en__isnull=True)
    elif estado == 'leidos':
        consulta = consulta.filter(leido_en__isnull=False)
    return consulta.order_by('prioridad', '-comunicado__creado', '-comunicado__pk')


# ---------------------------------------------------------------------------
# Gestión y seguimiento
# ---------------------------------------------------------------------------
def con_estadisticas(consulta):
    """Los comunicados con su total de destinatarios, cuántos lo leyeron y cuántos hay de cada tipo (cada destinatario
    es una persona distinta: el envío no admite repetidos). Los archivos se cuentan aparte para no multiplicar filas."""
    adjuntos = Adjunto.objects.filter(comunicado=OuterRef('pk')).order_by().values('comunicado').annotate(n=Count('pk')).values('n')
    return consulta.annotate(
        total=Count('destinatarios'),
        leidos=Count('destinatarios', filter=Q(destinatarios__leido_en__isnull=False)),
        n_tutores=Count('destinatarios', filter=Q(destinatarios__tipo=Destinatario.TUTOR)),
        n_estudiantes=Count('destinatarios', filter=Q(destinatarios__tipo=Destinatario.ESTUDIANTE)),
        n_profesores=Count('destinatarios', filter=Q(destinatarios__tipo=Destinatario.PROFESOR)),
        n_adjuntos=Coalesce(Subquery(adjuntos, output_field=IntegerField()), 0),
    )


def preparar(comunicado):
    """Agrega a un comunicado con estadísticas lo que muestran la tarjeta y el detalle."""
    conteos = {Destinatario.TUTOR: comunicado.n_tutores, Destinatario.ESTUDIANTE: comunicado.n_estudiantes,
               Destinatario.PROFESOR: comunicado.n_profesores}
    comunicado.resumen_destinatarios = resumen_por_tipo(conteos)
    comunicado.desglose = [(tipo, conteos[tipo], cantidad(conteos[tipo], tipo)) for tipo in ORDEN_DE_TIPOS if conteos[tipo]]
    comunicado.porcentaje = porcentaje(comunicado.leidos, comunicado.total)
    comunicado.pendientes = comunicado.total - comunicado.leidos
    return comunicado


def gestionables(usuario, vista):
    """'enviados': los propios; 'gestion': todos los del colegio (solo el administrador)."""
    consulta = Comunicado.objects.visibles().select_related('autor')
    if vista == 'gestion' and es_administrador(usuario):
        return consulta
    return consulta.filter(autor=usuario)


def filtrar_por_estado(consulta, estado, ahora=None):
    if estado == 'activos':
        return consulta.activos(ahora)
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
