"""Pantallas de la mensajería. Son las mismas vistas en el sistema (/mensajes/) y en los dos portales
(/portal/estudiantes/mensajes/ y /portal/tutores/mensajes/): cambian la cuenta (`Cuenta`), la plantilla base y la
protección (permisos del sistema o la sesión del portal). Ver Mensajes/urls.py.
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO import portales
from CISAHUAYO.permisos import requiere_alguno

from . import limpieza, reglas
from .models import Conversacion, ImagenMensaje, Mensaje, Participante
from .tiempo_real import datos_de_mensaje

registro = logging.getLogger(__name__)
# Las imágenes del editor: fotos JPG, PNG o WEBP; los documentos adjuntos: PDF (el tipo real se revisa con su contenido:
# Conducta.forms.validar_archivo)
ACEPTA_IMAGENES = '.jpg,.jpeg,.png,.webp'
ACEPTA_DOCUMENTOS = '.pdf'


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
    return reglas.familias_de([participante.tutor]).get(participante.tutor_id) or 'Tutor'


def _dia(fecha, hoy):
    if fecha == hoy:
        return 'Hoy'
    if fecha == hoy - timedelta(days=1):
        return 'Ayer'
    return date_format(fecha, 'l j \\d\\e F' if fecha.year == hoy.year else 'j \\d\\e F \\d\\e Y').capitalize()


def _hora_corta(momento):
    momento, hoy = timezone.localtime(momento), timezone.localdate()
    if momento.date() == hoy:
        return momento.strftime('%H:%M')
    return momento.strftime('%d/%m' if momento.year == hoy.year else '%d/%m/%Y')


def _resultado(mensaje, cuenta):
    """Un mensaje encontrado al buscar, como lo usa static/js/mensajes.js (el fragmento ya viene escapado)."""
    return {
        'conversacion': mensaje.conversacion_id, 'id': mensaje.pk, 'mio': mensaje.mio,
        'nombre': mensaje.otro.nombre, 'iniciales': mensaje.otro.iniciales, 'tipo': mensaje.otro.tipo.lower(),
        'fragmento': str(mensaje.fragmento), 'hora': _hora_corta(mensaje.creado),
        'url': f"{cuenta.url('conversacion', mensaje.conversacion_id)}?mensaje={mensaje.pk}#mensaje-{mensaje.pk}",
    }


def _pantalla(request, cuenta, conversacion=None, **extra):
    participante = cuenta.participante
    limpieza.limpiar_si_toca()   # una vez al día: los archivos que se subieron y nunca se enviaron
    busqueda = request.GET.get('q', '').strip()
    bandeja, siguientes = reglas.pagina_de_bandeja(participante, despues=request.GET.get('despues') or None)
    contexto = {
        **cuenta.contexto, 'base': cuenta.base, 'espacio': cuenta.espacio, 'yo': participante,
        'bandeja': bandeja, 'siguientes': siguientes, 'conversacion': conversacion, 'busqueda': busqueda,
        'contactos': reglas.contactos(participante, busqueda) if busqueda else None,
        'encontrados': [_resultado(m, cuenta) for m in reglas.buscar_mensajes(participante, busqueda)] if busqueda else None,
        'hoy_iso': timezone.localdate().isoformat(),
        'urls': {
            'inicio': cuenta.url('inicio'), 'contactos': cuenta.url('contactos'), 'nueva': cuenta.url('nueva'),
            'resumen': cuenta.url('resumen'), 'buscar': cuenta.url('buscar'), 'conversaciones': cuenta.url('conversaciones'),
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
    antes, destacado = request.GET.get('antes', ''), request.GET.get('mensaje', '')
    if destacado.isdigit():   # abierta en un mensaje encontrado al buscar: los de antes y después de él
        mensajes, hay_anteriores, hay_posteriores = reglas.ventana(conversacion, int(destacado))
    else:
        mensajes, hay_anteriores = reglas.historial(conversacion, antes=int(antes) if antes.isdigit() else None)
        hay_posteriores = antes.isdigit() and conversacion.mensajes.filter(pk__gte=int(antes)).exists()
    reglas.con_documentos(mensajes, lambda documento: cuenta.url('documento', documento))
    leido_hasta = reglas.leido_por_el_otro(conversacion, participante)
    hoy = timezone.localdate()
    ultimo_leido_mio = None
    for mensaje in mensajes:
        mensaje.mio = mensaje.autor_id == participante.pk
        mensaje.leido = mensaje.mio and mensaje.pk <= leido_hasta
        if mensaje.leido:
            mensaje.texto_leido = reglas.texto_de_lectura(mensaje.leido_en)
            ultimo_leido_mio = mensaje.pk
        mensaje.dia = _dia(timezone.localtime(mensaje.creado).date(), hoy)
        mensaje.cita = reglas.cita_de(mensaje)
        if reglas.se_puede_editar(mensaje, participante):
            mensaje.editable_hasta = (mensaje.creado + timedelta(minutes=reglas.MINUTOS_PARA_EDITAR)).isoformat()
        # Con formato: el HTML limpio otra vez al mostrarlo (Mensajes/enriquecido.py), con las imágenes de su espacio
        mensaje.html_visible = mark_safe(reglas.html_visible(mensaje, participante)) if mensaje.html else ''
    otro = reglas.el_otro(conversacion, participante)
    return _pantalla(
        request, cuenta, conversacion,
        otro=otro, descripcion_otro=descripcion(otro) if otro else '', mensajes=mensajes, hay_anteriores=hay_anteriores,
        hay_posteriores=hay_posteriores, destacado=int(destacado) if destacado.isdigit() else None,
        primero=mensajes[0].pk if mensajes else None, leido_hasta=leido_hasta, ultimo_leido_mio=ultimo_leido_mio,
        puede_escribir=reglas.puede_escribir_en(conversacion, participante), maximo=Mensaje.MAXIMO,
        url_enviar=cuenta.url('enviar', conversacion.pk), url_leida=cuenta.url('leida', conversacion.pk),
        url_imagenes=cuenta.url('imagen_subir', conversacion.pk), acepta_imagenes=ACEPTA_IMAGENES,
        url_documentos=cuenta.url('documento_subir', conversacion.pk), acepta_documentos=ACEPTA_DOCUMENTOS,
        maximo_imagen_mb=ImagenMensaje.TAMANO_MAXIMO_MB, documentos_por_mensaje=ImagenMensaje.DOCUMENTOS_POR_MENSAJE,
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
        mensaje = reglas.enviar(conversacion, cuenta.participante, request.POST.get('texto', ''), request.POST.get('html', ''),
                                documentos=request.POST.getlist('documentos'), responde_a=request.POST.get('responde_a'))
    except reglas.MensajeRechazado as rechazo:
        if _quiere_json(request):
            return JsonResponse({'error': str(rechazo)}, status=400)
        messages.error(request, str(rechazo))
        return redirect(cuenta.url('conversacion', conversacion.pk))
    if _quiere_json(request):
        return JsonResponse(datos_de_mensaje(mensaje, cuenta.participante))
    return redirect(f"{cuenta.url('conversacion', conversacion.pk)}#mensaje-{mensaje.pk}")


@require_POST
def editar(request, pk):
    """Corrige el texto de un mensaje propio en sus primeros minutos (reglas.editar). Responde con el mensaje."""
    cuenta = request.mensajeria
    mensaje = Mensaje.objects.select_related('conversacion', 'autor').filter(
        pk=pk, conversacion__miembros__participante=cuenta.participante).first()
    if mensaje is None:
        raise Http404('No existe ese mensaje.')
    try:
        reglas.editar(mensaje, cuenta.participante, request.POST.get('texto', ''))
    except reglas.MensajeRechazado as rechazo:
        return JsonResponse({'error': str(rechazo)}, status=400)
    return JsonResponse(datos_de_mensaje(mensaje, cuenta.participante))


def _subir(request, pk, campo, documento):
    """Sube un archivo a la conversación, aún sin mensaje (solo lo ve quien lo subió hasta que lo envía): una imagen del
    editor (`documento` False) o un PDF adjunto. Responde {id, url, nombre, tamano}."""
    from Conducta.forms import validar_archivo

    cuenta = request.mensajeria
    conversacion = _conversacion(cuenta, pk)
    if not reglas.puede_escribir_en(conversacion, cuenta.participante):
        return JsonResponse({'error': 'Ya no puedes escribir en esta conversación.'}, status=403)
    archivo = request.FILES.get(campo)
    if archivo is None:
        return JsonResponse({'error': 'Elige un documento PDF.' if documento else 'Elige una imagen.'}, status=400)
    try:
        tipo = validar_archivo(archivo)
        if documento and tipo != ImagenMensaje.DOCUMENTO:
            raise ValidationError(f'«{archivo.name}»: solo se pueden adjuntar documentos PDF.')
        if not documento and not tipo.startswith('image/'):
            raise ValidationError(f'«{archivo.name}»: solo se pueden insertar imágenes JPG, PNG o WEBP.')
    except ValidationError as error:
        return JsonResponse({'error': ' '.join(error.messages)}, status=400)
    # Los que se subieron hace más de un día y nunca se enviaron, se borran (archivo incluido)
    limpieza.limpiar_pendientes(conversacion=conversacion, autor=cuenta.participante)
    pendientes = ImagenMensaje.objects.filter(conversacion=conversacion, autor=cuenta.participante, mensaje__isnull=True)
    if pendientes.count() >= ImagenMensaje.PENDIENTES_MAXIMAS:
        return JsonResponse({'error': 'Tienes demasiados archivos sin enviar en esta conversación. Envía o quita algunos.'}, status=400)
    try:
        subido = ImagenMensaje.objects.create(
            conversacion=conversacion, autor=cuenta.participante, archivo=archivo, tipo=tipo, tamano=archivo.size,
            nombre_original=(archivo.name or ('documento.pdf' if documento else 'imagen'))[:200])
    except Exception:
        registro.exception('No se pudo guardar el archivo del mensaje en la conversación %s', conversacion.pk)
        return JsonResponse({'error': 'No se pudo guardar el archivo. Inténtalo de nuevo.'}, status=500)
    return JsonResponse(subido.como_dict(cuenta.url('documento' if documento else 'imagen', subido.pk)))


@require_POST
def imagen_subir(request, pk):
    """Una imagen del editor; el editor la inserta como <img data-imagen="id">."""
    return _subir(request, pk, 'imagen', documento=False)


@require_POST
def documento_subir(request, pk):
    """Un documento PDF adjunto: se envía con el mensaje (documentos=id) y se muestra debajo del texto."""
    return _subir(request, pk, 'documento', documento=True)


def _entregar(request, pk, documento):
    """Entrega un archivo de mensaje a quien es miembro de su conversación (antes de enviarse, solo a quien lo subió)."""
    from Conducta.views import entregar_archivo

    participante = request.mensajeria.participante
    archivos = ImagenMensaje.objects.filter(pk=pk, conversacion__miembros__participante=participante)
    archivos = archivos.filter(tipo=ImagenMensaje.DOCUMENTO) if documento else archivos.filter(tipo__startswith='image/')
    archivo = archivos.first()
    if archivo is None or (archivo.mensaje_id is None and archivo.autor_id != participante.pk):
        raise Http404('No existe ese archivo.')
    respuesta = entregar_archivo(archivo.archivo, archivo.nombre_original, archivo.tipo, descargar=request.GET.get('descargar') == '1')
    respuesta['Cache-Control'] = 'private, max-age=3600'
    return respuesta


@require_GET
def imagen(request, pk):
    return _entregar(request, pk, documento=False)


@require_GET
def documento(request, pk):
    """El PDF se abre en el navegador (con ?descargar=1, se descarga)."""
    return _entregar(request, pk, documento=True)


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
def buscar(request):
    """Los mensajes de sus conversaciones que tienen el texto buscado (la búsqueda de la bandeja)."""
    cuenta = request.mensajeria
    texto = request.GET.get('q', '').strip()[:100]
    return JsonResponse({'mensajes': [_resultado(m, cuenta) for m in reglas.buscar_mensajes(cuenta.participante, texto)]})


@require_GET
def conversaciones(request):
    """Las conversaciones que siguen en la bandeja («Ver más conversaciones»): {html, siguientes}."""
    cuenta = request.mensajeria
    bandeja, siguientes = reglas.pagina_de_bandeja(cuenta.participante, despues=request.GET.get('despues') or None)
    actual = request.GET.get('actual', '')
    html = render_to_string('mensajes/_conversaciones.html', {
        'bandeja': bandeja, 'espacio': cuenta.espacio, 'hoy_iso': timezone.localdate().isoformat(),
        'actual': int(actual) if actual.isdigit() else None,
    }, request=request)
    return JsonResponse({'html': html, 'siguientes': siguientes or ''})


@require_GET
def resumen(request):
    """El total sin leer y los avisos de la campana (al reconectarse, para ponerse al día)."""
    from .context_processors import datos_de_avisos
    cuenta = request.mensajeria
    return JsonResponse(datos_de_avisos(cuenta.participante, cuenta.espacio, como_json=True))
