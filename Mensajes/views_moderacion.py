"""Pantallas de la moderación de la mensajería (solo en el sistema, con `Mensajes.moderar`: exclusivo del administrador).

- Búsqueda en todas las conversaciones, por persona, texto o fechas.
- Los mensajes reportados por quienes los recibieron (2026-10-27): retirarlos o descartar el reporte.
- Todas las conversaciones del colegio, por persona o por con quién son (2026-10-27), y las que esperan respuesta.
- Una conversación completa, de solo lectura (no la marca como leída: quien modera no es miembro).
- Retirar un mensaje: confirmación y borrado completo (Mensajes/moderacion.py).
Las imágenes de los mensajes se entregan aquí por su propia ruta (las de la mensajería solo las ven los miembros).
"""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_permisos

from . import enriquecido, moderacion, reglas
from .forms import FiltroConversacionesForm, FiltroModeracionForm
from .models import ConfiguracionMensajes, Conversacion, ImagenMensaje, Mensaje, Participante, ReporteMensaje
from .moderacion import MODERAR


def _contexto(seccion, **extra):
    """Lo que comparten las pantallas con pestañas (templates/mensajes/_moderacion_pestanas.html)."""
    return {'moderacion_seccion': seccion, 'reportados_pendientes': moderacion.reportados_pendientes(),
            'por_pagina_defecto': POR_PAGINA_DEFECTO, 'opciones_por_pagina': OPCIONES_POR_PAGINA, **extra}


def _volver(request):
    """A dónde regresar después de retirar: la búsqueda o la conversación de donde se abrió."""
    inicio = reverse('mensajes:moderacion')
    pedido = request.POST.get('volver') or request.GET.get('volver') or ''
    return pedido if pedido.startswith(inicio) and '//' not in pedido else inicio


def _url_de_archivo(pk):
    return reverse('mensajes:moderacion_imagen', args=[pk])


def _html(mensaje):
    """El HTML limpio del mensaje, con sus imágenes por la ruta de la moderación ('' si no tiene formato)."""
    if not mensaje.html:
        return ''
    return mark_safe(enriquecido.presentar(mensaje.html, _url_de_archivo))


@requiere_permisos(MODERAR)
@require_GET
def buscar(request):
    filtro = FiltroModeracionForm(request.GET)
    datos = filtro.activos
    contexto = _contexto('buscar', filtro=filtro, filtros_activos=datos)
    if datos:   # sin criterios no se lista ningún mensaje: para recorrer, están las conversaciones (abajo)
        pagina, rango, por_pagina = paginar(request, moderacion.buscar(**datos))
        pagina.object_list = moderacion.con_destinatarios(pagina.object_list)
        for mensaje in pagina.object_list:
            mensaje.fragmento = reglas.resaltar(mensaje.texto, datos.get('texto', ''))
        contexto.update(pagina=pagina, rango_paginas=rango, por_pagina=por_pagina)
    return render(request, 'mensajes/moderacion.html', contexto)


@requiere_permisos(MODERAR)
@require_GET
def reportados(request):
    """Los mensajes que reportaron quienes los recibieron, del reporte más reciente al más antiguo: quién lo reportó y
    por qué, y las acciones (verlo en la conversación, retirarlo o descartar el reporte)."""
    pagina, rango, por_pagina = paginar(request, moderacion.reportados())
    pagina.object_list = moderacion.con_destinatarios(pagina.object_list)
    reglas.con_documentos(pagina.object_list, _url_de_archivo)
    return render(request, 'mensajes/moderacion_reportados.html', _contexto(
        'reportados', pagina=pagina, rango_paginas=rango, por_pagina=por_pagina))


@requiere_permisos(MODERAR)
@require_POST
def descartar(request, pk):
    """El mensaje reportado no es inapropiado: se borran sus reportes y sigue en la conversación."""
    mensaje = get_object_or_404(Mensaje, pk=pk)
    if moderacion.descartar_reportes(mensaje):
        messages.success(request, 'Se descartó el reporte. El mensaje sigue en la conversación.')
    return redirect(_volver(request))


@requiere_permisos(MODERAR)
@require_GET
def conversaciones(request):
    """Todas las conversaciones del colegio (con mensajes), de la más reciente a la más antigua: por persona, por con
    quién son (con estudiantes, con tutores o entre el personal) y las que esperan respuesta (de la que más lleva
    esperando a la que menos, con cuántos días hábiles). Sin ese filtro, un aviso dice cuántas esperan."""
    filtro = FiltroConversacionesForm(request.GET)
    datos = filtro.activos
    esperando = datos.get('estado') == moderacion.ESPERANDO
    pagina, rango, por_pagina = paginar(request, moderacion.conversaciones(**datos))
    pagina.object_list = moderacion.con_miembros(pagina.object_list)
    if esperando:
        moderacion.con_espera(pagina.object_list)
    return render(request, 'mensajes/moderacion_conversaciones.html', _contexto(
        'conversaciones', filtro=filtro, filtros_activos=datos, pagina=pagina, rango_paginas=rango, por_pagina=por_pagina,
        esperando=esperando, dias_para_responder=ConfiguracionMensajes.actual().dias_para_responder,
        esperan=None if esperando else moderacion.conversaciones(estado=moderacion.ESPERANDO).count()))


@requiere_permisos(MODERAR)
@require_GET
def conversacion(request, pk):
    conversacion = get_object_or_404(Conversacion, pk=pk)
    destacado = request.GET.get('mensaje', '')
    alrededor = destacado or request.GET.get('alrededor', '')
    mensajes, hay_anteriores, hay_posteriores = moderacion.ventana(conversacion, alrededor=int(alrededor) if alrededor.isdigit() else None)
    # Las familias y los estudiantes a la izquierda; el personal, a la derecha (como en su propia pantalla)
    miembros = sorted(moderacion.miembros_de(conversacion), key=lambda p: (p.tipo == Participante.SISTEMA, p.pk))
    derecha = miembros[-1].pk if len(miembros) > 1 else None
    reglas.con_documentos(mensajes, _url_de_archivo)
    reportes = {}
    for reporte in ReporteMensaje.objects.filter(mensaje__in=[m.pk for m in mensajes]):
        reportes[reporte.mensaje_id] = reportes.get(reporte.mensaje_id, 0) + 1
    for mensaje in mensajes:
        mensaje.veces_reportado = reportes.get(mensaje.pk, 0)
        mensaje.a_la_derecha = mensaje.autor_id == derecha
        mensaje.html_visible = _html(mensaje)
        mensaje.dia = timezone.localtime(mensaje.creado).date()
    return render(request, 'mensajes/moderacion_conversacion.html', {
        'conversacion': conversacion, 'miembros': miembros, 'mensajes': mensajes,
        'hay_anteriores': hay_anteriores, 'hay_posteriores': hay_posteriores,
        'destacado': int(destacado) if destacado.isdigit() else None, 'volver': _volver(request),
        'aqui': request.get_full_path(),
    })


@requiere_permisos(MODERAR)
def retirar(request, pk):
    mensaje = get_object_or_404(Mensaje.objects.select_related(*moderacion.CON_CUENTA), pk=pk)
    volver = _volver(request)
    if request.method == 'POST':
        moderacion.retirar(mensaje)
        messages.success(request, 'Se retiró el mensaje. Ya no aparece para ninguna de las dos personas.')
        return redirect(volver)
    mensaje.para = moderacion.con_destinatarios([mensaje])[0].para
    mensaje.html_visible = _html(mensaje)
    reglas.con_documentos([mensaje], _url_de_archivo)
    return render(request, 'mensajes/moderacion_retirar.html', {
        'mensaje': mensaje, 'volver': volver, 'archivos': mensaje.imagenes.count(),
    })


@requiere_permisos(MODERAR)
@require_GET
def imagen(request, pk):
    """La imagen o el documento de un mensaje enviado (lo que aún no se envía es solo de quien lo subió: ni la moderación
    lo ve)."""
    from Conducta.views import entregar_archivo

    imagen = ImagenMensaje.objects.filter(pk=pk, mensaje__isnull=False).first()
    if imagen is None:
        raise Http404('No existe esa imagen.')
    respuesta = entregar_archivo(imagen.archivo, imagen.nombre_original, imagen.tipo, descargar=request.GET.get('descargar') == '1')
    respuesta['Cache-Control'] = 'private, no-store'   # si se retira, que no quede guardada en el navegador
    return respuesta
