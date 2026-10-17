"""Pantallas de los comunicados.

En el sistema (/comunicados/): las pestañas «Recibidos» (un profesor), «Enviados» (quien da seguimiento a los suyos) y
«Todos los comunicados» (la gestión global del administrador, aparte de su bandeja personal); crear, el detalle con su
seguimiento, los archivos y eliminar. En los portales (/portal/estudiantes/comunicados/ y /portal/tutores/comunicados/):
solo lo recibido, con las mismas vistas de recepción y la sesión del portal (Comunicados/urls.py).

Cada vista revisa en el servidor quién la pide: lo que no le toca responde 404 (ni siquiera se dice que existe).
"""
import uuid
from dataclasses import dataclass, field
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from CISAHUAYO import portales
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos

from . import reglas
from .alcance import ELIMINAR, ENVIAR, GESTIONAR, RECIBIR, SEGUIMIENTO, SIN_NIVELES, alcance_de, es_administrador
from .forms import ACEPTA, AYUDA_DE_ARCHIVOS, TAMANO_MAXIMO_MB, ComunicadoForm
from .models import Adjunto, Comunicado, Destinatario

POR_PAGINA = 20
VISTAS = {'recibidos': 'Recibidos', 'enviados': 'Enviados', 'gestion': 'Todos los comunicados'}
ESTADOS_DE_GESTION = (('todos', 'Todos'), ('activos', 'Activos'), ('caducados', 'Caducados'))
ESTADOS_DE_RECIBIDOS = (('todos', 'Todos'), ('pendientes', 'Sin leer'), ('leidos', 'Leídos'))


@dataclass
class Bandeja:
    """Quién recibe en esta pantalla: un profesor en el sistema o la cuenta de un portal."""
    lector: object
    base: str
    espacio: str
    contexto: dict = field(default_factory=dict)

    def url(self, nombre, *args):
        return reverse(f'{self.espacio}:{nombre}', args=args)


def _quiere_json(request):
    return 'application/json' in request.headers.get('Accept', '')


def _contexto_de_archivos():
    return {'acepta': ACEPTA, 'maximo_mb': TAMANO_MAXIMO_MB, 'maximo_archivos': Comunicado.MAXIMO_ADJUNTOS,
            'ayuda_archivos': AYUDA_DE_ARCHIVOS, 'maximo_titulo': Comunicado.MAXIMO_TITULO,
            'maximo_descripcion': Comunicado.MAXIMO_DESCRIPCION}


def _formulario(request, form=None):
    """Lo que necesita el formulario de crear (en la ventana del listado o en su propia página)."""
    alcance = alcance_de(request.user)
    return {
        'form': form, 'clave_envio': (form.data.get('clave_envio') if form is not None else '') or uuid.uuid4(),
        'alcance': alcance, 'url_crear': reverse('comunicados:crear'), 'url_destinatarios': reverse('comunicados:destinatarios'),
        'hoy': timezone.localdate(), **_contexto_de_archivos(),
    }


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
def _vistas_de(usuario):
    lector = reglas.lector_de_usuario(usuario)
    vistas = []
    if lector is not None:
        vistas.append('recibidos')
    if usuario.has_perm(SEGUIMIENTO):
        vistas.append('enviados')
    if es_administrador(usuario):
        vistas.append('gestion')
    return vistas or ['recibidos'], lector


def _vista_inicial(vistas):
    for preferida in ('gestion', 'enviados', 'recibidos'):
        if preferida in vistas:
            return preferida
    return vistas[0]


def _fecha_pedida(request):
    fecha = parse_date(request.GET.get('fecha', '') or '') if request.GET.get('fecha') else None
    return fecha if fecha and fecha <= timezone.localdate() else None


@require_GET
@requiere_alguno(RECIBIR, SEGUIMIENTO, ENVIAR, GESTIONAR)
def inicio(request):
    usuario = request.user
    vistas, lector = _vistas_de(usuario)
    vista = request.GET.get('vista')
    if vista not in vistas:
        vista = _vista_inicial(vistas)
    texto = request.GET.get('q', '').strip()
    fecha = _fecha_pedida(request)
    estados = ESTADOS_DE_RECIBIDOS if vista == 'recibidos' else ESTADOS_DE_GESTION
    estado = request.GET.get('estado', 'todos')
    if estado not in dict(estados):
        estado = 'todos'

    if vista == 'recibidos':
        consulta = reglas.recibidos(lector, estado) if lector is not None else Destinatario.objects.none()
        consulta = reglas.buscar(consulta, texto, ('comunicado__titulo', 'comunicado__descripcion'))
        if fecha:
            consulta = consulta.filter(comunicado__creado__date=fecha)
    else:
        consulta = reglas.gestionables(usuario, vista)
        consulta = reglas.filtrar_por_estado(consulta, estado)
        consulta = reglas.buscar(consulta, texto)
        if fecha:
            consulta = consulta.filter(creado__date=fecha)
        consulta = reglas.con_estadisticas(consulta).order_by('-creado', '-pk')

    pagina, rango, por_pagina = paginar(request, consulta, por_defecto=POR_PAGINA)
    if vista != 'recibidos':
        for comunicado in pagina.object_list:
            reglas.preparar(comunicado)
            comunicado.eliminable = reglas.puede_eliminar(usuario, comunicado)

    pendientes = lector.pendientes()[0] if lector is not None else 0
    alcance = alcance_de(usuario)
    puede_crear = usuario.has_perm(ENVIAR)
    contexto = {
        'vista': vista, 'vistas': [(clave, VISTAS[clave]) for clave in vistas], 'estado': estado, 'estados': estados,
        'texto': texto, 'fecha': fecha, 'pagina': pagina, 'rango': rango, 'por_pagina': por_pagina, 'opciones': OPCIONES_POR_PAGINA,
        'lector': lector, 'pendientes': pendientes, 'hoy': timezone.localdate(), 'ahora': timezone.now(),
        'puede_crear': puede_crear, 'sin_niveles': puede_crear and not alcance.puede_enviar, 'mensaje_sin_niveles': SIN_NIVELES,
        'alcance': alcance, 'filtrado': bool(texto or fecha or estado != 'todos'),
        'seleccionable': vista != 'recibidos' and any(getattr(c, 'eliminable', False) for c in pagina.object_list),
        'base': 'base.html', 'espacio': 'comunicados',
    }
    if puede_crear and alcance.puede_enviar:
        contexto.update(_formulario(request))
    return render(request, 'comunicados/inicio.html', contexto)


# ---------------------------------------------------------------------------
# Crear
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
@requiere_permisos(ENVIAR)
def crear(request):
    alcance = alcance_de(request.user)
    if not alcance.puede_enviar:
        if _quiere_json(request):
            return JsonResponse({'errores': {'__all__': [SIN_NIVELES]}}, status=403)
        messages.warning(request, SIN_NIVELES)
        return redirect('comunicados:inicio')
    if request.method == 'GET':
        return render(request, 'comunicados/crear.html', _formulario(request))

    form = ComunicadoForm(request.POST, archivos=request.FILES.getlist('archivos'))
    errores = None
    if form.is_valid():
        datos = form.cleaned_data
        try:
            comunicado, nuevo = reglas.enviar(
                request.user, titulo=datos['titulo'], descripcion=datos['descripcion'], urgente=datos['urgente'],
                expira=datos['expira'], clave_envio=datos['clave_envio'], seleccion=datos['destinatarios'],
                archivos=form.archivos_validos,
            )
        except reglas.EnvioRechazado as rechazo:
            errores = {rechazo.campo or '__all__': [rechazo.mensaje]}
        else:
            if nuevo:
                total = comunicado.destinatarios.count()
                messages.success(request, f'Se publicó «{comunicado.titulo}» para {total} destinatario{"s" if total != 1 else ""}. '
                                          'En su detalle verás quién lo ha leído.')
            destino = f"{reverse('comunicados:inicio')}?vista=enviados"
            if _quiere_json(request):
                return JsonResponse({'ok': True, 'redirect': destino, 'id': comunicado.pk})
            return redirect(destino)
    else:
        errores = form.errores()

    if _quiere_json(request):
        return JsonResponse({'errores': errores}, status=400)
    contexto = _formulario(request, form)
    contexto.update(errores=errores, errores_generales=errores.get('__all__', []))
    return render(request, 'comunicados/crear.html', contexto, status=400)


@require_GET
@requiere_permisos(ENVIAR)
def destinatarios(request):
    """Las personas que puede elegir (todo su alcance: el selector filtra y marca en el navegador)."""
    alcance = alcance_de(request.user)
    if not alcance.puede_enviar:
        return JsonResponse({'error': SIN_NIVELES}, status=403)
    respuesta = JsonResponse(alcance.universo())
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


# ---------------------------------------------------------------------------
# Detalle y seguimiento (autor y administrador)
# ---------------------------------------------------------------------------
def _comunicado_gestionable(request, pk):
    consulta = reglas.con_estadisticas(Comunicado.objects.visibles().select_related('autor'))
    comunicado = get_object_or_404(consulta, pk=pk)
    if not reglas.puede_dar_seguimiento(request.user, comunicado):
        raise Http404('No existe ese comunicado.')
    return reglas.preparar(comunicado)


@require_GET
@requiere_alguno(SEGUIMIENTO, GESTIONAR)
def detalle(request, pk):
    """El seguimiento: consultarlo nunca marca como leído a nadie."""
    comunicado = _comunicado_gestionable(request, pk)
    destinatarios = list(comunicado.destinatarios.select_related('alumno', 'tutor', 'profesor').order_by('tipo', 'pk'))
    destinatarios.sort(key=lambda d: (reglas.ORDEN_DE_TIPOS.index(d.tipo), d.leido_en is not None, d.nombre.lower()))
    contexto = {
        'comunicado': comunicado, 'destinatarios': destinatarios, 'adjuntos': list(comunicado.adjuntos.all()),
        'gestion': True, 'puede_eliminar': reglas.puede_eliminar(request.user, comunicado), 'ahora': timezone.now(),
        'url_adjunto': 'comunicados:adjunto', 'base': 'base.html', 'espacio': 'comunicados',
        'volver': request.GET.get('volver') if (request.GET.get('volver') or '').startswith('/comunicados/') else reverse('comunicados:inicio'),
    }
    plantilla = 'comunicados/_detalle.html' if request.GET.get('parcial') == '1' else 'comunicados/detalle.html'
    respuesta = render(request, plantilla, contexto)
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


# ---------------------------------------------------------------------------
# Recepción (profesores en el sistema; estudiantes y tutores en su portal)
# ---------------------------------------------------------------------------
def _bandeja_del_sistema(request):
    return Bandeja(reglas.lector_de_usuario(request.user), 'base.html', 'comunicados')


def _recibido(request, bandeja, pk):
    """El comunicado tal como lo ve quien lo recibe. Abrirlo bien guarda su primera lectura."""
    if bandeja.lector is None:
        raise Http404('No existe ese comunicado.')
    destinatario = get_object_or_404(bandeja.lector.destinatarios().select_related('comunicado__autor'), comunicado_id=pk)
    reglas.marcar_leido(destinatario)
    comunicado = destinatario.comunicado
    contexto = {
        **bandeja.contexto, 'comunicado': comunicado, 'destinatario': destinatario, 'adjuntos': list(comunicado.adjuntos.all()),
        'gestion': False, 'url_adjunto': f'{bandeja.espacio}:adjunto', 'base': bandeja.base, 'espacio': bandeja.espacio,
        'pendientes': bandeja.lector.pendientes()[0], 'volver': bandeja.url('inicio'),
    }
    plantilla = 'comunicados/_detalle.html' if request.GET.get('parcial') == '1' else 'comunicados/detalle.html'
    respuesta = render(request, plantilla, contexto)
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


@require_GET
@requiere_permisos(RECIBIR)
def recibido(request, pk):
    return _recibido(request, _bandeja_del_sistema(request), pk)


def _entregar(adjunto, request):
    from Conducta.views import entregar_archivo
    return entregar_archivo(adjunto.archivo, adjunto.nombre_original, adjunto.tipo, descargar=request.GET.get('descargar') == '1')


@require_GET
@requiere_alguno(RECIBIR, SEGUIMIENTO, GESTIONAR)
def adjunto(request, pk):
    """El autor y el administrador, siempre (también caducado); un destinatario, mientras siga activo."""
    adjunto = get_object_or_404(Adjunto.objects.select_related('comunicado'), pk=pk, comunicado__eliminado=False)
    if not reglas.puede_dar_seguimiento(request.user, adjunto.comunicado):
        lector = reglas.lector_de_usuario(request.user)
        if lector is None or not lector.destinatarios().filter(comunicado_id=adjunto.comunicado_id).exists():
            raise Http404('No existe ese archivo.')
    return _entregar(adjunto, request)


# ---------------------------------------------------------------------------
# Eliminar
# ---------------------------------------------------------------------------
def _volver_al_listado(request):
    vista = request.POST.get('vista') or request.GET.get('vista')
    url = reverse('comunicados:inicio')
    return f'{url}?vista={vista}' if vista in VISTAS else url


@require_http_methods(['GET', 'POST'])
@requiere_alguno(ELIMINAR, GESTIONAR)
def eliminar(request, pk):
    comunicado = _comunicado_gestionable(request, pk)
    if not reglas.puede_eliminar(request.user, comunicado):
        raise PermissionDenied('No puedes eliminar este comunicado.')
    if request.method == 'POST':
        reglas.eliminar(request.user, comunicado)
        messages.success(request, f'Se eliminó «{comunicado.titulo}»: ya no lo ven sus destinatarios. Queda registrado en el historial.')
        return redirect(_volver_al_listado(request))
    return render(request, 'comunicados/eliminar.html', {'comunicados': [comunicado], 'vista': request.GET.get('vista', '')})


@require_POST
@requiere_alguno(ELIMINAR, GESTIONAR)
def eliminar_varios(request):
    pedidos = [int(pk) for pk in request.POST.getlist('comunicados') if pk.isdigit()]
    eliminados = 0
    for comunicado in Comunicado.objects.visibles().filter(pk__in=pedidos):
        if reglas.puede_eliminar(request.user, comunicado) and reglas.eliminar(request.user, comunicado):
            eliminados += 1
    if eliminados:
        messages.success(request, f'Se eliminaron {eliminados} comunicado{"s" if eliminados != 1 else ""}: ya no los ven sus destinatarios. '
                                  'Quedan registrados en el historial.' if eliminados != 1 else
                         'Se eliminó 1 comunicado: ya no lo ven sus destinatarios. Queda registrado en el historial.')
    else:
        messages.info(request, 'No se eliminó ningún comunicado: elige al menos uno de los que puedes eliminar.')
    return redirect(_volver_al_listado(request))


# ---------------------------------------------------------------------------
# Portales
# ---------------------------------------------------------------------------
ESPACIO_DE_PORTAL = {portales.ESTUDIANTE: 'portal_estudiantes:comunicados', portales.TUTOR: 'portal_tutores:comunicados'}


def para_portal(tipo):
    """Una vista de recepción para las cuentas de un portal (su sesión: CISAHUAYO/portales.py)."""
    def decorador(vista):
        @wraps(vista)
        def envuelta(request, *args, **kwargs):
            request.bandeja = Bandeja(reglas.lector_de_portal(tipo, request.cuenta_portal), 'portales/base.html',
                                      ESPACIO_DE_PORTAL[tipo], portales.contexto(request))
            return vista(request, *args, **kwargs)
        return portales.portal_requerido(tipo)(envuelta)
    return decorador


@require_GET
def portal_inicio(request):
    bandeja = request.bandeja
    texto = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', 'todos')
    if estado not in dict(ESTADOS_DE_RECIBIDOS):
        estado = 'todos'
    fecha = _fecha_pedida(request)
    consulta = reglas.buscar(reglas.recibidos(bandeja.lector, estado), texto, ('comunicado__titulo', 'comunicado__descripcion'))
    if fecha:
        consulta = consulta.filter(comunicado__creado__date=fecha)
    pagina, rango, por_pagina = paginar(request, consulta, por_defecto=POR_PAGINA)
    return render(request, 'comunicados/inicio.html', {
        **bandeja.contexto, 'vista': 'recibidos', 'vistas': [], 'estado': estado, 'estados': ESTADOS_DE_RECIBIDOS,
        'texto': texto, 'fecha': fecha, 'pagina': pagina, 'rango': rango, 'por_pagina': por_pagina, 'opciones': OPCIONES_POR_PAGINA,
        'lector': bandeja.lector, 'pendientes': bandeja.lector.pendientes()[0], 'hoy': timezone.localdate(), 'ahora': timezone.now(),
        'puede_crear': False, 'filtrado': bool(texto or fecha or estado != 'todos'), 'seleccionable': False,
        'base': bandeja.base, 'espacio': bandeja.espacio,
    })


@require_GET
def portal_recibido(request, pk):
    return _recibido(request, request.bandeja, pk)


@require_GET
def portal_adjunto(request, pk):
    adjunto = get_object_or_404(Adjunto.objects.select_related('comunicado'), pk=pk, comunicado__eliminado=False)
    if not request.bandeja.lector.destinatarios().filter(comunicado_id=adjunto.comunicado_id).exists():
        raise Http404('No existe ese archivo.')
    return _entregar(adjunto, request)
