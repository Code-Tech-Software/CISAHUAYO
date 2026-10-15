"""Pantallas de la mensajería. Son las mismas vistas en el sistema (/mensajes/) y en los dos portales
(/portal/estudiantes/mensajes/ y /portal/tutores/mensajes/): cambian la cuenta (`Cuenta`), la plantilla base y la
protección (permisos del sistema o la sesión del portal). Ver Mensajes/urls.py.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO import portales
from CISAHUAYO.permisos import requiere_alguno

from . import reglas
from .models import Conversacion, Mensaje, Participante
from .tiempo_real import datos_de_mensaje


@dataclass
class Cuenta:
    participante: Participante
    base: str                 # plantilla que extienden las pantallas
    espacio: str              # espacio de rutas («mensajes», «portal_estudiantes:mensajes»…)
    contexto: dict = field(default_factory=dict)

    def url(self, nombre, *args):
        return reverse(f'{self.espacio}:{nombre}', args=args)


def para_sistema(vista):
    """Una vista para los usuarios del sistema con la mensajería."""
    @wraps(vista)
    def envuelta(request, *args, **kwargs):
        request.mensajeria = Cuenta(reglas.de_usuario(request.user), 'base.html', reglas.ESPACIO[Participante.SISTEMA])
        return vista(request, *args, **kwargs)
    return requiere_alguno(reglas.USAR, reglas.FAMILIAS)(envuelta)


def para_portal(tipo):
    """Una vista para las cuentas de un portal (su sesión: CISAHUAYO/portales.py)."""
    def decorador(vista):
        @wraps(vista)
        def envuelta(request, *args, **kwargs):
            participante = reglas.de_portal(tipo, request.cuenta_portal)
            request.mensajeria = Cuenta(participante, 'portales/base.html', reglas.ESPACIO[participante.tipo], portales.contexto(request))
            return vista(request, *args, **kwargs)
        return portales.portal_requerido(tipo)(envuelta)
    return decorador


def _quiere_json(request):
    return 'application/json' in request.headers.get('Accept', '')


def _conversacion(cuenta, pk):
    """La conversación, si la persona es miembro (si no, 404: ni siquiera se dice que existe)."""
    conversacion = Conversacion.objects.filter(pk=pk, miembros__participante=cuenta.participante).first()
    if conversacion is None:
        raise Http404('No existe esa conversación.')
    return conversacion


def descripcion(participante):
    """Quién es la otra persona, en pocas palabras (bajo su nombre)."""
    if participante.tipo == Participante.SISTEMA:
        from Usuarios.docentes import profesor_de
        from Usuarios.seguridad import rol_de
        rol = rol_de(participante.usuario)
        return 'Docente' if profesor_de(participante.usuario) is not None and (rol is None or rol.es_docente) else (rol.nombre if rol else 'Personal del colegio')
    if participante.tipo == Participante.ESTUDIANTE:
        inscripcion = participante.alumno.inscripciones.filter(activa=True, ciclo__activo=True).select_related('grupo__grado', 'grupo__nombre').first()
        return f'Estudiante · {inscripcion.grupo}' if inscripcion else 'Estudiante'
    return 'Tutor'


def _dia(fecha, hoy):
    if fecha == hoy:
        return 'Hoy'
    if fecha == hoy - timedelta(days=1):
        return 'Ayer'
    return date_format(fecha, 'l j \\d\\e F' if fecha.year == hoy.year else 'j \\d\\e F \\d\\e Y').capitalize()


def _pantalla(request, cuenta, conversacion=None, **extra):
    participante = cuenta.participante
    busqueda = request.GET.get('q', '').strip()
    contexto = {
        **cuenta.contexto, 'base': cuenta.base, 'espacio': cuenta.espacio, 'yo': participante,
        'bandeja': reglas.bandeja(participante), 'conversacion': conversacion, 'busqueda': busqueda,
        'contactos': reglas.contactos(participante, busqueda) if busqueda else None,
        'hoy_iso': timezone.localdate().isoformat(),
        'urls': {
            'inicio': cuenta.url('inicio'), 'contactos': cuenta.url('contactos'), 'nueva': cuenta.url('nueva'),
            'resumen': cuenta.url('resumen'),
        },
        **extra,
    }
    return render(request, 'mensajes/bandeja.html', contexto)


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
@require_GET
def bandeja(request):
    return _pantalla(request, request.mensajeria)


@require_GET
def conversacion(request, pk):
    cuenta = request.mensajeria
    participante = cuenta.participante
    conversacion = _conversacion(cuenta, pk)
    reglas.marcar_leida(conversacion, participante)   # al consultarla, queda leída
    antes = request.GET.get('antes', '')
    mensajes, hay_anteriores = reglas.historial(conversacion, antes=int(antes) if antes.isdigit() else None)
    leido_hasta = reglas.leido_por_el_otro(conversacion, participante)
    hoy = timezone.localdate()
    for mensaje in mensajes:
        mensaje.mio = mensaje.autor_id == participante.pk
        mensaje.leido = mensaje.mio and mensaje.pk <= leido_hasta
        mensaje.dia = _dia(timezone.localtime(mensaje.creado).date(), hoy)
    otro = reglas.el_otro(conversacion, participante)
    return _pantalla(
        request, cuenta, conversacion,
        otro=otro, descripcion_otro=descripcion(otro) if otro else '', mensajes=mensajes, hay_anteriores=hay_anteriores,
        primero=mensajes[0].pk if mensajes else None, leido_hasta=leido_hasta,
        puede_escribir=reglas.puede_escribir_en(conversacion, participante), maximo=Mensaje.MAXIMO,
        url_enviar=cuenta.url('enviar', conversacion.pk), url_leida=cuenta.url('leida', conversacion.pk),
    )


@require_POST
def nueva(request):
    """Abre (o retoma) la conversación con la persona elegida en la búsqueda."""
    cuenta = request.mensajeria
    destino = reglas.de_clave(request.POST.get('destinatario', ''))
    try:
        if destino is None:
            raise reglas.MensajeRechazado('No encontramos a esa persona.')
        conversacion = reglas.conversacion_con(cuenta.participante, destino)
    except reglas.MensajeRechazado as rechazo:
        messages.error(request, str(rechazo))
        return redirect(cuenta.url('inicio'))
    return redirect(cuenta.url('conversacion', conversacion.pk))


@require_POST
def enviar(request, pk):
    cuenta = request.mensajeria
    conversacion = _conversacion(cuenta, pk)
    try:
        mensaje = reglas.enviar(conversacion, cuenta.participante, request.POST.get('texto', ''))
    except reglas.MensajeRechazado as rechazo:
        if _quiere_json(request):
            return JsonResponse({'error': str(rechazo)}, status=400)
        messages.error(request, str(rechazo))
        return redirect(cuenta.url('conversacion', conversacion.pk))
    if _quiere_json(request):
        return JsonResponse(datos_de_mensaje(mensaje, cuenta.participante))
    return redirect(f"{cuenta.url('conversacion', conversacion.pk)}#mensaje-{mensaje.pk}")


@require_POST
def leida(request, pk):
    cuenta = request.mensajeria
    reglas.marcar_leida(_conversacion(cuenta, pk), cuenta.participante)
    return JsonResponse({'no_leidos': reglas.no_leidos(cuenta.participante)})


@require_GET
def contactos(request):
    cuenta = request.mensajeria
    texto = request.GET.get('q', '').strip()
    return JsonResponse({'contactos': [c.como_dict() for c in reglas.contactos(cuenta.participante, texto)]})


@require_GET
def resumen(request):
    """El total sin leer y los avisos de la campana (al reconectarse, para ponerse al día)."""
    from .context_processors import datos_de_avisos
    cuenta = request.mensajeria
    return JsonResponse(datos_de_avisos(cuenta.participante, cuenta.espacio, como_json=True))
