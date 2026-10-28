"""Pantallas de los comunicados.

En el sistema (/comunicados/): las pestañas «Recibidos» (un profesor o alguien del personal), «Enviados» (quien da
seguimiento a los suyos) y «Todos los comunicados» (la gestión global del administrador, aparte de su bandeja personal);
crear (también a partir de otro: «Usar como base»), corregir, el detalle con su seguimiento (lectura por grupo,
respuestas, «Recordar a los pendientes» y la lista en Excel), los archivos, las imágenes del texto y eliminar. En los
portales (/portal/estudiantes/comunicados/ y /portal/tutores/comunicados/): solo lo recibido, con las mismas vistas de
recepción y la sesión del portal (Comunicados/urls.py). Quien recibe puede responder (si se pide) y bajar el evento a
su calendario.

Cada vista revisa en el servidor quién la pide: lo que no le toca responde 404 (ni siquiera se dice que existe).
"""
import json
import re
import uuid
from dataclasses import dataclass, field
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from CISAHUAYO import portales
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from Mensajes import enriquecido

from . import avisos, reglas
from .alcance import ELIMINAR, ENVIAR, GESTIONAR, RECIBIR, SEGUIMIENTO, SIN_NIVELES, alcance_de, es_administrador
from .forms import ACEPTA, AYUDA_DE_ARCHIVOS, CLAVES, TAMANO_MAXIMO_MB, ComunicadoForm
from .models import Adjunto, Comunicado, Destinatario, ImagenComunicado

POR_PAGINA = 20
VISTAS = {'recibidos': 'Recibidos', 'enviados': 'Enviados', 'gestion': 'Todos los comunicados'}
ESTADOS_DE_GESTION = (('todos', 'Todos'), ('activos', 'Activos'), ('programados', 'Programados'), ('caducados', 'Caducados'))
ESTADOS_DE_RECIBIDOS = (('todos', 'Todos'), ('pendientes', 'Sin leer'), ('por_responder', 'Por responder'), ('leidos', 'Leídos'))
ACEPTA_IMAGENES = '.jpg,.jpeg,.png,.webp'


@dataclass
class Bandeja:
    """Quién recibe en esta pantalla: un profesor o alguien del personal en el sistema, o la cuenta de un portal."""
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
            'maximo_descripcion': Comunicado.MAXIMO_DESCRIPCION, 'maximo_opciones': Comunicado.MAXIMO_OPCIONES,
            'categorias': Comunicado.CATEGORIAS, 'respuestas': Comunicado.RESPUESTAS,
            'url_imagenes': reverse('comunicados:imagen_subir'), 'acepta_imagenes': ACEPTA_IMAGENES,
            'maximo_imagen_mb': ImagenComunicado.TAMANO_MAXIMO_MB}


def _url_de_imagen_del_sistema(pk):
    return reverse('comunicados:imagen', args=[pk])


def _copia_del_texto(usuario, base):
    """El HTML de `base` para el editor, con sus imágenes copiadas como imágenes nuevas (todavía sin enviar) de quien lo
    usa como base: así el comunicado nuevo tiene las suyas y las ven sus propios destinatarios."""
    if not base.html:
        return reglas.html_para_editar(base, _url_de_imagen_del_sistema)
    copias = {}
    for imagen in base.imagenes.all():
        try:
            nueva = ImagenComunicado.objects.create(
                autor=usuario, archivo=reglas._copiar_archivo(imagen.archivo, imagen.nombre_original),
                nombre_original=imagen.nombre_original, tipo=imagen.tipo, tamano=imagen.tamano)
        except Exception:   # el archivo original ya no está: la imagen no se copia
            continue
        copias[imagen.pk] = nueva.pk
    html = re.sub(r'data-imagen="(\d+)"', lambda m: f'data-imagen="{copias.get(int(m.group(1)), 0)}"', base.html)
    return enriquecido.limpiar(html, imagenes_validas=set(copias.values()), url_de_imagen=_url_de_imagen_del_sistema)[0]


def _seleccion_de(comunicado):
    """Los destinatarios de un comunicado como los guarda el selector ({"tutores": [ids], …})."""
    campos = {Destinatario.TUTOR: 'tutor_id', Destinatario.ESTUDIANTE: 'alumno_id', Destinatario.PROFESOR: 'profesor_id',
              Destinatario.PERSONAL: 'usuario_id'}
    seleccion = {clave: [] for clave in CLAVES}
    tipos = {tipo: clave for clave, tipo in CLAVES.items()}
    for fila in comunicado.destinatarios.values('tipo', *campos.values()):
        seleccion[tipos[fila['tipo']]].append(fila[campos[fila['tipo']]])
    return seleccion


def _inicial_de(comunicado, usuario, copiar):
    """Lo que el formulario muestra ya escrito: el comunicado que se corrige (`copiar` False) o el que se usa como base."""
    datos = {
        'titulo': comunicado.titulo, 'descripcion': comunicado.descripcion, 'urgente': comunicado.urgente,
        'categoria': comunicado.categoria, 'fijado': comunicado.fijado, 'respuesta': comunicado.respuesta,
        'pregunta': comunicado.pregunta, 'opciones': [o.texto for o in comunicado.opciones.all()],
        'evento_fecha': comunicado.evento_fecha.isoformat() if comunicado.evento_fecha else '',
        'evento_hora_inicio': f'{comunicado.evento_hora_inicio:%H:%M}' if comunicado.evento_hora_inicio else '',
        'evento_hora_fin': f'{comunicado.evento_hora_fin:%H:%M}' if comunicado.evento_hora_fin else '',
        'evento_lugar': comunicado.evento_lugar,
        'html': _copia_del_texto(usuario, comunicado) if copiar else reglas.html_para_editar(comunicado, _url_de_imagen_del_sistema),
    }
    if copiar:
        datos['destinatarios'] = json.dumps(_seleccion_de(comunicado))
    else:
        expira = timezone.localtime(comunicado.expira) if comunicado.expira else None
        publicado = timezone.localtime(comunicado.publicado_en)
        datos.update(expira_fecha=expira.date().isoformat() if expira else '', expira_hora=f'{expira:%H:%M}' if expira else '')
        if comunicado.programado:
            datos.update(publicar_fecha=publicado.date().isoformat(), publicar_hora=f'{publicado:%H:%M}')
    return datos


class _Datos:
    """Un formulario «de mentira» para que la plantilla lea los valores iniciales igual que los de un envío fallido."""
    def __init__(self, datos):
        self.data = datos


def _formulario(request, form=None, base=None, comunicado=None):
    """Lo que necesita el formulario de crear (en la ventana del listado o en su propia página) o de corregir."""
    alcance = alcance_de(request.user)
    if form is None and (base is not None or comunicado is not None):
        form = _Datos(_inicial_de(comunicado or base, request.user, copiar=comunicado is None))
    datos = getattr(form, 'data', {}) if form is not None else {}
    opciones = datos.getlist('opciones') if hasattr(datos, 'getlist') else list(datos.get('opciones') or [])
    previos = list((comunicado or base).adjuntos.all()) if (comunicado or base) is not None else []
    contexto = {
        'form': form, 'clave_envio': (datos.get('clave_envio') if form is not None else '') or uuid.uuid4(),
        'alcance': alcance, 'url_crear': reverse('comunicados:crear'), 'url_destinatarios': reverse('comunicados:destinatarios'),
        'hoy': timezone.localdate(), 'opciones_iniciales': opciones + [''] * max(0, 2 - len(opciones)),
        'base_comunicado': base, 'edicion': comunicado, 'adjuntos_previos': previos,
        **_contexto_de_archivos(),
    }
    # El texto con formato que el editor muestra al abrir (limpio otra vez: también el de un envío que falló)
    html = datos.get('html') or ''
    if html:
        validas = set(ImagenComunicado.objects.filter(autor=request.user, comunicado__isnull=True).values_list('pk', flat=True))
        if comunicado is not None:
            validas |= set(comunicado.imagenes.values_list('pk', flat=True))
        html = enriquecido.limpiar(html, imagenes_validas=validas, url_de_imagen=_url_de_imagen_del_sistema)[0]
    contexto['html_inicial'] = html
    if comunicado is not None:
        contexto['url_crear'] = reverse('comunicados:editar', args=[comunicado.pk])
        contexto['programable'] = comunicado.avisado_en is None and comunicado.programado
        contexto['resumen_edicion'] = reglas.resumen_por_tipo(dict(comunicado.destinatarios.values_list('tipo').annotate(n=Count('pk'))))
    else:
        contexto['programable'] = True
    return contexto


def _categoria_pedida(request):
    categoria = request.GET.get('categoria', '')
    return categoria if categoria in dict(Comunicado.CATEGORIAS) else ''


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
    avisos.publicar_si_toca()
    usuario = request.user
    vistas, lector = _vistas_de(usuario)
    vista = request.GET.get('vista')
    if vista not in vistas:
        vista = _vista_inicial(vistas)
    texto = request.GET.get('q', '').strip()
    fecha = _fecha_pedida(request)
    categoria = _categoria_pedida(request)
    estados = ESTADOS_DE_RECIBIDOS if vista == 'recibidos' else ESTADOS_DE_GESTION
    estado = request.GET.get('estado', 'todos')
    if estado not in dict(estados):
        estado = 'todos'

    if vista == 'recibidos':
        consulta = reglas.recibidos(lector, estado, categoria) if lector is not None else Destinatario.objects.none()
        consulta = reglas.buscar(consulta, texto, ('comunicado__titulo', 'comunicado__descripcion'))
        if fecha:
            consulta = consulta.filter(comunicado__publicado_en__date=fecha)
    else:
        consulta = reglas.gestionables(usuario, vista)
        consulta = reglas.filtrar_por_estado(consulta, estado)
        consulta = reglas.buscar(consulta, texto)
        if categoria:
            consulta = consulta.filter(categoria=categoria)
        if fecha:
            consulta = consulta.filter(publicado_en__date=fecha)
        consulta = reglas.con_estadisticas(consulta).order_by('-publicado_en', '-pk')

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
        'texto': texto, 'fecha': fecha, 'categoria': categoria, 'categorias': Comunicado.CATEGORIAS,
        'pagina': pagina, 'rango': rango, 'por_pagina': por_pagina, 'opciones': OPCIONES_POR_PAGINA,
        'lector': lector, 'pendientes': pendientes, 'hoy': timezone.localdate(), 'ahora': timezone.now(),
        'puede_crear': puede_crear, 'sin_niveles': puede_crear and not alcance.puede_enviar, 'mensaje_sin_niveles': SIN_NIVELES,
        'alcance': alcance, 'filtrado': bool(texto or fecha or categoria or estado != 'todos'),
        'seleccionable': vista != 'recibidos' and any(getattr(c, 'eliminable', False) for c in pagina.object_list),
        'base': 'base.html', 'espacio': 'comunicados',
    }
    if puede_crear and alcance.puede_enviar:
        contexto.update(_formulario(request))
    return render(request, 'comunicados/inicio.html', contexto)


# ---------------------------------------------------------------------------
# Crear, usar como base y corregir
# ---------------------------------------------------------------------------
def _base_pedida(request):
    """El comunicado que se usa como base (?base=N o el campo «base»): uno al que quien envía puede dar seguimiento."""
    pk = request.POST.get('base') or request.GET.get('base') or ''
    if not str(pk).isdigit():
        return None
    base = Comunicado.objects.visibles().filter(pk=pk).first()
    return base if base is not None and reglas.puede_dar_seguimiento(request.user, base) else None


def _errores_de(form, rechazo=None):
    if rechazo is not None:
        return {rechazo.campo or '__all__': [rechazo.mensaje]}
    return form.errores()


def _responder_errores(request, plantilla, contexto, errores):
    if _quiere_json(request):
        return JsonResponse({'errores': errores}, status=400)
    contexto.update(errores=errores, errores_generales=errores.get('__all__', []))
    return render(request, plantilla, contexto, status=400)


@require_http_methods(['GET', 'POST'])
@requiere_permisos(ENVIAR)
def crear(request):
    alcance = alcance_de(request.user)
    if not alcance.puede_enviar:
        if _quiere_json(request):
            return JsonResponse({'errores': {'__all__': [SIN_NIVELES]}}, status=403)
        messages.warning(request, SIN_NIVELES)
        return redirect('comunicados:inicio')
    base = _base_pedida(request)
    if request.method == 'GET':
        return render(request, 'comunicados/crear.html', _formulario(request, base=base))

    form = ComunicadoForm(request.POST, archivos=request.FILES.getlist('archivos'))
    rechazo = None
    if form.is_valid():
        datos = form.cleaned_data
        copiar = []
        if base is not None:
            ids = [int(pk) for pk in request.POST.getlist('copiar_adjuntos') if pk.isdigit()]
            copiar = list(base.adjuntos.filter(pk__in=ids))
        try:
            comunicado, nuevo = reglas.enviar(
                request.user, titulo=datos['titulo'], descripcion=datos['descripcion'], html=datos['html'], urgente=datos['urgente'],
                expira=datos['expira'], clave_envio=datos['clave_envio'], seleccion=datos['destinatarios'],
                archivos=form.archivos_validos, categoria=datos['categoria'], fijado=datos['fijado'], publicar_en=datos['publicar_en'],
                respuesta=datos['respuesta'], pregunta=datos['pregunta'], opciones=datos['opciones'], evento=datos['evento'],
                copiar_adjuntos=copiar,
            )
        except reglas.EnvioRechazado as error:
            rechazo = error
        else:
            if nuevo:
                total = comunicado.destinatarios.count()
                if comunicado.avisado_en is None:
                    cuando = timezone.localtime(comunicado.publicado_en)
                    messages.success(request, f'Se programó «{comunicado.titulo}» para {total} destinatario{"s" if total != 1 else ""}: '
                                              f'se publicará el {cuando:%d/%m/%Y} a las {cuando:%H:%M}.')
                else:
                    messages.success(request, f'Se publicó «{comunicado.titulo}» para {total} destinatario{"s" if total != 1 else ""}. '
                                              'En su detalle verás quién lo ha leído.')
            destino = f"{reverse('comunicados:inicio')}?vista=enviados"
            if _quiere_json(request):
                return JsonResponse({'ok': True, 'redirect': destino, 'id': comunicado.pk})
            return redirect(destino)
    return _responder_errores(request, 'comunicados/crear.html', _formulario(request, form, base=base), _errores_de(form, rechazo))


@require_http_methods(['GET', 'POST'])
@requiere_permisos(ENVIAR)
def editar(request, pk):
    """Corregir un comunicado ya enviado: el texto, el título, la urgencia, las fechas, la categoría, si va fijado, el
    evento y los archivos (los destinatarios y la respuesta que se pide no cambian)."""
    comunicado = get_object_or_404(Comunicado.objects.visibles(), pk=pk)
    if not reglas.puede_editar(request.user, comunicado):
        raise Http404('No existe ese comunicado.')
    if request.method == 'GET':
        return render(request, 'comunicados/editar.html', _formulario(request, comunicado=comunicado))
    form = ComunicadoForm(request.POST, archivos=request.FILES.getlist('archivos'), para_editar=True)
    rechazo = None
    if form.is_valid():
        datos = form.cleaned_data
        try:
            reglas.editar(
                request.user, comunicado, titulo=datos['titulo'], descripcion=datos['descripcion'], html=datos['html'],
                urgente=datos['urgente'], expira=datos['expira'], categoria=datos['categoria'], fijado=datos['fijado'],
                evento=datos['evento'], publicar_en=datos['publicar_en'], conservar_adjuntos=request.POST.getlist('conservar_adjuntos'),
                archivos=form.archivos_validos,
            )
        except reglas.EnvioRechazado as error:
            rechazo = error
        else:
            messages.success(request, f'Se guardaron los cambios de «{comunicado.titulo}». Quienes ya lo recibieron lo ven corregido.')
            destino = reverse('comunicados:detalle', args=[comunicado.pk])
            if _quiere_json(request):
                return JsonResponse({'ok': True, 'redirect': destino, 'id': comunicado.pk})
            return redirect(destino)
    return _responder_errores(request, 'comunicados/editar.html', _formulario(request, form, comunicado=comunicado), _errores_de(form, rechazo))


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


@require_POST
@requiere_permisos(ENVIAR)
def imagen_subir(request):
    """Una imagen para el texto con formato; el editor la inserta como <img data-imagen="id">. Hasta que se envía el
    comunicado solo la ve quien la subió."""
    from Conducta.forms import validar_archivo
    archivo = request.FILES.get('imagen')
    if archivo is None:
        return JsonResponse({'error': 'Elige una imagen.'}, status=400)
    try:
        tipo = validar_archivo(archivo)
        if not tipo.startswith('image/'):
            raise ValidationError(f'«{archivo.name}»: solo se pueden insertar imágenes JPG, PNG o WEBP.')
    except ValidationError as error:
        return JsonResponse({'error': ' '.join(error.messages)}, status=400)
    if ImagenComunicado.objects.filter(autor=request.user, comunicado__isnull=True).count() >= 30:
        return JsonResponse({'error': 'Tienes demasiadas imágenes sin enviar. Envía el comunicado o quita algunas.'}, status=400)
    imagen = ImagenComunicado.objects.create(autor=request.user, archivo=archivo, tipo=tipo, tamano=archivo.size,
                                             nombre_original=(archivo.name or 'imagen')[:200])
    return JsonResponse({'id': imagen.pk, 'url': _url_de_imagen_del_sistema(imagen.pk)})


def _entregar_imagen(imagen):
    from Conducta.views import entregar_archivo
    respuesta = entregar_archivo(imagen.archivo, imagen.nombre_original, imagen.tipo, descargar=False)
    respuesta['Cache-Control'] = 'private, max-age=3600'
    return respuesta


@require_GET
@requiere_alguno(RECIBIR, SEGUIMIENTO, ENVIAR, GESTIONAR)
def imagen(request, pk):
    """Una imagen del texto: sin enviar, a quien la subió; enviada, a quien da seguimiento al comunicado o lo recibe."""
    imagen = get_object_or_404(ImagenComunicado.objects.select_related('comunicado'), pk=pk)
    if imagen.comunicado_id is None:
        if imagen.autor_id != request.user.pk:
            raise Http404('No existe esa imagen.')
    elif imagen.comunicado.eliminado or not reglas.puede_dar_seguimiento(request.user, imagen.comunicado):
        lector = reglas.lector_de_usuario(request.user)
        if imagen.comunicado.eliminado or lector is None or not lector.destinatarios().filter(comunicado_id=imagen.comunicado_id).exists():
            raise Http404('No existe esa imagen.')
    return _entregar_imagen(imagen)


# ---------------------------------------------------------------------------
# Detalle y seguimiento (autor y administrador)
# ---------------------------------------------------------------------------
def _comunicado_gestionable(request, pk):
    consulta = reglas.con_estadisticas(Comunicado.objects.visibles().select_related('autor'))
    comunicado = get_object_or_404(consulta, pk=pk)
    if not reglas.puede_dar_seguimiento(request.user, comunicado):
        raise Http404('No existe ese comunicado.')
    return reglas.preparar(comunicado)


def _destinatarios_de(comunicado):
    destinatarios = list(comunicado.destinatarios.select_related('alumno', 'tutor', 'profesor', 'usuario', 'opcion', 'grupo__grado', 'grupo__nombre'))
    destinatarios.sort(key=lambda d: (reglas.ORDEN_DE_TIPOS.index(d.tipo), d.leido_en is not None, d.nombre.lower()))
    return destinatarios


@require_GET
@requiere_alguno(SEGUIMIENTO, GESTIONAR)
def detalle(request, pk):
    """El seguimiento: consultarlo nunca marca como leído a nadie."""
    comunicado = _comunicado_gestionable(request, pk)
    destinatarios = _destinatarios_de(comunicado)
    por_grupo = reglas.lectura_por_grupo(destinatarios)
    contexto = {
        'comunicado': comunicado, 'destinatarios': destinatarios, 'adjuntos': list(comunicado.adjuntos.all()),
        'contenido': reglas.contenido_visible(comunicado, _url_de_imagen_del_sistema),
        'gestion': True, 'puede_eliminar': reglas.puede_eliminar(request.user, comunicado), 'ahora': timezone.now(),
        'puede_editar': reglas.puede_editar(request.user, comunicado), 'puede_usar_de_base': request.user.has_perm(ENVIAR),
        # Solo si alguien cuenta en un grupo (a solo profesores o personal no hay nada que desglosar)
        'por_grupo': por_grupo if any(fila['es_grupo'] for fila in por_grupo) else [],
        'respuestas': reglas.resumen_de_respuestas(comunicado, destinatarios) if comunicado.pide_respuesta else None,
        'por_recordar': reglas.por_recordar(comunicado).count(), 'motivo_sin_recordar': reglas.motivo_para_no_recordar(comunicado),
        'url_adjunto': 'comunicados:adjunto', 'url_calendario': reverse('comunicados:calendario', args=[comunicado.pk]),
        'base': 'base.html', 'espacio': 'comunicados',
        'volver': request.GET.get('volver') if (request.GET.get('volver') or '').startswith('/comunicados/') else reverse('comunicados:inicio'),
    }
    plantilla = 'comunicados/_detalle.html' if request.GET.get('parcial') == '1' else 'comunicados/detalle.html'
    respuesta = render(request, plantilla, contexto)
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


@require_POST
@requiere_alguno(SEGUIMIENTO, GESTIONAR)
def recordar(request, pk):
    """«Recordar a los pendientes»: el aviso otra vez (en tiempo real y push) a quienes no lo han leído o respondido."""
    comunicado = _comunicado_gestionable(request, pk)
    try:
        cuantos = reglas.recordar(request.user, comunicado)
    except reglas.EnvioRechazado as rechazo:
        if _quiere_json(request):
            return JsonResponse({'error': rechazo.mensaje}, status=400)
        messages.warning(request, rechazo.mensaje)
    else:
        aviso = f'Se recordó el comunicado a {cuantos} persona{"s" if cuantos != 1 else ""}.'
        if _quiere_json(request):
            return JsonResponse({'ok': True, 'mensaje': aviso, 'cuantos': cuantos})
        messages.success(request, aviso)
    return redirect('comunicados:detalle', pk=comunicado.pk)


@require_GET
@requiere_alguno(SEGUIMIENTO, GESTIONAR)
def exportar(request, pk):
    """La lista de lectura (y de respuestas) en Excel, con una hoja por grupo."""
    from CISAHUAYO.xlsx import ENCABEZADO, SECCION, TITULO, Celda, Hoja, libro
    comunicado = _comunicado_gestionable(request, pk)
    destinatarios = _destinatarios_de(comunicado)
    publicado = timezone.localtime(comunicado.publicado_en)
    encabezados = ['Nombre', 'Tipo', 'Grupo', 'Detalle', 'Leído', 'Fecha de lectura']
    if comunicado.pide_respuesta:
        encabezados += ['Respuesta', 'Fecha de respuesta']
    filas = [
        [Celda(comunicado.titulo, TITULO)],
        [f'Publicado el {publicado:%d/%m/%Y %H:%M} · {reglas.nombre_de_usuario(comunicado.autor)}'],
        [f'Leído por {comunicado.leidos} de {comunicado.total} ({comunicado.porcentaje} %)'],
        [],
        [Celda(texto, ENCABEZADO) for texto in encabezados],
    ]
    for destinatario in destinatarios:
        fila = [destinatario.nombre, destinatario.get_tipo_display(), destinatario.grupo.corto if destinatario.grupo_id else '',
                destinatario.detalle, 'Sí' if destinatario.leido else 'No',
                timezone.localtime(destinatario.leido_en).replace(tzinfo=None) if destinatario.leido_en else None]
        if comunicado.pide_respuesta:
            fila += [destinatario.texto_de_respuesta or 'Sin responder',
                     timezone.localtime(destinatario.respondido_en).replace(tzinfo=None) if destinatario.respondido_en else None]
        filas.append(fila)
    por_grupo = [[Celda('Lectura por grupo', TITULO)], [],
                 [Celda(texto, ENCABEZADO) for texto in ['Grupo', 'Destinatarios', 'Leídos', '% de lectura'] + (['Respondieron'] if comunicado.pide_respuesta else [])]]
    for grupo in reglas.lectura_por_grupo(destinatarios):
        por_grupo.append([grupo['nombre'], grupo['total'], grupo['leidos'], grupo['porcentaje']] + ([grupo['respondidos']] if comunicado.pide_respuesta else []))
    if comunicado.pide_respuesta:
        resumen = reglas.resumen_de_respuestas(comunicado, destinatarios)
        por_grupo += [[], [Celda('Respuestas', SECCION)]] + [[fila['texto'], fila['cuantos']] for fila in resumen['filas']]
        por_grupo.append(['Sin responder', resumen['sin_responder']])
    contenido = libro([Hoja('Lectura', filas, anchos=[34, 14, 12, 40, 8, 18, 22, 18]), Hoja('Por grupo', por_grupo, anchos=[30, 14, 10, 14, 14])])
    respuesta = HttpResponse(contenido, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="comunicado-{comunicado.pk}-lectura.xlsx"'
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


# ---------------------------------------------------------------------------
# Recepción (profesores y personal en el sistema; estudiantes y tutores en su portal)
# ---------------------------------------------------------------------------
def _bandeja_del_sistema(request):
    return Bandeja(reglas.lector_de_usuario(request.user), 'base.html', 'comunicados')


def _copia(bandeja, pk):
    if bandeja.lector is None:
        raise Http404('No existe ese comunicado.')
    return get_object_or_404(bandeja.lector.destinatarios().select_related('comunicado__autor', 'opcion'), comunicado_id=pk)


def _recibido(request, bandeja, pk):
    """El comunicado tal como lo ve quien lo recibe. Abrirlo bien guarda su primera lectura."""
    destinatario = _copia(bandeja, pk)
    reglas.marcar_leido(destinatario)
    comunicado = destinatario.comunicado
    url_de_imagen = (lambda imagen: bandeja.url('imagen', imagen))
    contexto = {
        **bandeja.contexto, 'comunicado': comunicado, 'destinatario': destinatario, 'adjuntos': list(comunicado.adjuntos.all()),
        'contenido': reglas.contenido_visible(comunicado, url_de_imagen), 'opciones_encuesta': list(comunicado.opciones.all()),
        'gestion': False, 'url_adjunto': f'{bandeja.espacio}:adjunto', 'base': bandeja.base, 'espacio': bandeja.espacio,
        'url_responder': bandeja.url('responder', comunicado.pk), 'url_calendario': bandeja.url('calendario', comunicado.pk),
        'url_agenda': _url_de_la_agenda(bandeja.espacio, comunicado),
        'pendientes': bandeja.lector.pendientes()[0], 'volver': bandeja.url('inicio'),
    }
    plantilla = 'comunicados/_detalle.html' if request.GET.get('parcial') == '1' else 'comunicados/detalle.html'
    respuesta = render(request, plantilla, contexto)
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


def _url_de_la_agenda(espacio, comunicado):
    if not comunicado.tiene_evento:
        return ''
    nombre = {'comunicados': 'agenda:calendario', 'portal_estudiantes:comunicados': 'portal_estudiantes:agenda:calendario',
              'portal_tutores:comunicados': 'portal_tutores:agenda:calendario'}.get(espacio)
    try:
        return f'{reverse(nombre)}?mes={comunicado.evento_fecha:%Y-%m}' if nombre else ''
    except Exception:   # sin la agenda montada: solo no se ofrece el enlace
        return ''


def _responder(request, bandeja, pk):
    """La respuesta de quien lo recibe («Enterado», Sí / No o una opción de la encuesta)."""
    destinatario = _copia(bandeja, pk)
    try:
        reglas.responder(destinatario, request.POST.get('respuesta', ''))
    except reglas.EnvioRechazado as rechazo:
        if _quiere_json(request):
            return JsonResponse({'error': rechazo.mensaje}, status=400)
        messages.error(request, rechazo.mensaje)
    else:
        if _quiere_json(request):
            return JsonResponse({'ok': True, 'respuesta': destinatario.texto_de_respuesta, 'pendientes': bandeja.lector.pendientes()[0]})
        messages.success(request, 'Se guardó tu respuesta.')
    return redirect(bandeja.url('recibido', pk))


def _calendario(request, bandeja, pk, comunicado=None):
    """El evento del comunicado como archivo .ics (para agregarlo al calendario del teléfono o de la computadora)."""
    if comunicado is None:
        comunicado = _copia(bandeja, pk).comunicado
    if not comunicado.tiene_evento:
        raise Http404('Este comunicado no tiene evento.')
    url = request.build_absolute_uri(bandeja.url('recibido', comunicado.pk)) if bandeja is not None else ''
    respuesta = HttpResponse(reglas.calendario_ics(comunicado, url), content_type='text/calendar; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="comunicado-{comunicado.pk}.ics"'
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


@require_GET
@requiere_permisos(RECIBIR)
def recibido(request, pk):
    return _recibido(request, _bandeja_del_sistema(request), pk)


@require_POST
@requiere_permisos(RECIBIR)
def responder(request, pk):
    return _responder(request, _bandeja_del_sistema(request), pk)


@require_GET
@requiere_alguno(RECIBIR, SEGUIMIENTO, GESTIONAR)
def calendario(request, pk):
    """Quien lo recibe, mientras siga activo; el autor y el administrador, siempre."""
    gestionable = Comunicado.objects.visibles().filter(pk=pk).first()
    if gestionable is not None and reglas.puede_dar_seguimiento(request.user, gestionable):
        lector = reglas.lector_de_usuario(request.user)
        return _calendario(request, _bandeja_del_sistema(request) if lector else None, pk, comunicado=gestionable)
    return _calendario(request, _bandeja_del_sistema(request), pk)


def _resumen(lector, espacio):
    """Lo de la campana en JSON: cuántos no ha leído y los más recientes (static/js/comunicados-avisos.js lo pide al
    cargar la página, al llegar un aviso, al leer uno y al reconectarse)."""
    from .context_processors import datos_de_avisos
    avisos.publicar_si_toca()
    datos = datos_de_avisos(lector, espacio) if lector is not None else {'pendientes': 0, 'urgentes': 0, 'avisos': []}
    respuesta = JsonResponse(datos)
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


@require_GET
@requiere_permisos(RECIBIR)
def resumen(request):
    return _resumen(reglas.lector_de_usuario(request.user), 'comunicados')


def _entregar(adjunto, request):
    from Conducta.views import entregar_archivo
    return entregar_archivo(adjunto.archivo, adjunto.nombre_original, adjunto.tipo, descargar=request.GET.get('descargar') == '1')


@require_GET
@requiere_alguno(RECIBIR, SEGUIMIENTO, GESTIONAR, ENVIAR)
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
    avisos.publicar_si_toca()
    bandeja = request.bandeja
    texto = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', 'todos')
    if estado not in dict(ESTADOS_DE_RECIBIDOS):
        estado = 'todos'
    fecha = _fecha_pedida(request)
    categoria = _categoria_pedida(request)
    consulta = reglas.buscar(reglas.recibidos(bandeja.lector, estado, categoria), texto, ('comunicado__titulo', 'comunicado__descripcion'))
    if fecha:
        consulta = consulta.filter(comunicado__publicado_en__date=fecha)
    pagina, rango, por_pagina = paginar(request, consulta, por_defecto=POR_PAGINA)
    return render(request, 'comunicados/inicio.html', {
        **bandeja.contexto, 'vista': 'recibidos', 'vistas': [], 'estado': estado, 'estados': ESTADOS_DE_RECIBIDOS,
        'texto': texto, 'fecha': fecha, 'categoria': categoria, 'categorias': Comunicado.CATEGORIAS,
        'pagina': pagina, 'rango': rango, 'por_pagina': por_pagina, 'opciones': OPCIONES_POR_PAGINA,
        'lector': bandeja.lector, 'pendientes': bandeja.lector.pendientes()[0], 'hoy': timezone.localdate(), 'ahora': timezone.now(),
        'puede_crear': False, 'filtrado': bool(texto or fecha or categoria or estado != 'todos'), 'seleccionable': False,
        'base': bandeja.base, 'espacio': bandeja.espacio,
    })


@require_GET
def portal_recibido(request, pk):
    return _recibido(request, request.bandeja, pk)


@require_POST
def portal_responder(request, pk):
    return _responder(request, request.bandeja, pk)


@require_GET
def portal_calendario(request, pk):
    return _calendario(request, request.bandeja, pk)


@require_GET
def portal_resumen(request):
    return _resumen(request.bandeja.lector, request.bandeja.espacio)


@require_GET
def portal_adjunto(request, pk):
    adjunto = get_object_or_404(Adjunto.objects.select_related('comunicado'), pk=pk, comunicado__eliminado=False)
    if not request.bandeja.lector.destinatarios().filter(comunicado_id=adjunto.comunicado_id).exists():
        raise Http404('No existe ese archivo.')
    return _entregar(adjunto, request)


@require_GET
def portal_imagen(request, pk):
    imagen = get_object_or_404(ImagenComunicado, pk=pk, comunicado__isnull=False, comunicado__eliminado=False)
    if not request.bandeja.lector.destinatarios().filter(comunicado_id=imagen.comunicado_id).exists():
        raise Http404('No existe esa imagen.')
    return _entregar_imagen(imagen)
