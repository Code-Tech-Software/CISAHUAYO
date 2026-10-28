"""Agenda / Calendario: el calendario (por mes, por semana o la lista de próximos, con búsqueda), el detalle de un evento,
su archivo de calendario, la suscripción del teléfono, la vista para imprimir el mes y el registro, la edición y la
eliminación (solo el administrador: Agenda.gestionar), también de los eventos que se repiten y al duplicar uno.

El calendario es la misma pantalla en el sistema y en los portales (`base` cambia); qué eventos ve cada quien lo decide
Agenda/alcance.py en el servidor, y lo de otros módulos (días sin clases, comunicados, reuniones, fechas de
calificaciones y ciclo escolar) Agenda/fuentes.py. El mes (`mes=AAAA-MM`), la semana (`dia=AAAA-MM-DD`), el nivel
(`nivel=`), el tipo (`tipo=`), la vista (`vista=`) y la búsqueda (`q=`) van en la dirección. El detalle de un evento
como página es la misma dirección con `evento=`: consultar la agenda no pide permiso (cada quien ve lo suyo).
"""
from dataclasses import dataclass, field
from datetime import timedelta
from functools import wraps
from urllib.parse import parse_qsl, urlencode, urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.formats import date_format
from django.views.decorators.http import require_GET

from CISAHUAYO import portales
from CISAHUAYO.permisos import requiere_permisos

from . import alcance, calendario, fuentes, recordatorios, reglas
from .forms import EventoForm
from .fuentes import Persona
from .models import COLEGIO, COLORES, NOMBRE_DE_ALCANCE, NOMBRE_DE_TIPO, TIPOS, EventoAgenda, SuscripcionCalendario

ESPACIO_DE_PORTAL = {portales.TUTOR: 'portal_tutores:agenda', portales.ESTUDIANTE: 'portal_estudiantes:agenda'}
VISTAS = (('mes', 'Mes'), ('semana', 'Semana'), ('lista', 'Próximos'))
DIAS_DE_LA_LISTA = 60


@dataclass
class Espacio:
    persona: Persona
    base: str = 'base.html'
    nombre: str = 'agenda'              # espacio de nombres de las direcciones
    extra: dict = field(default_factory=dict)

    @property
    def vista(self):
        return self.persona.vista

    def url(self, nombre, *args):
        return reverse(f'{self.nombre}:{nombre}', args=args)


def _del_sistema(request):
    return Espacio(persona=Persona(usuario=request.user))


def para_portal(tipo):
    """Una vista de la agenda para las cuentas de un portal (su sesión: CISAHUAYO/portales.py)."""
    def decorador(vista):
        @wraps(vista)
        def envuelta(request, *args, **kwargs):
            cuenta = request.cuenta_portal
            persona = Persona(tutor=cuenta) if tipo == portales.TUTOR else Persona(alumno=cuenta)
            request.espacio_agenda = Espacio(persona=persona, base='portales/base.html', nombre=ESPACIO_DE_PORTAL[tipo],
                                             extra=portales.contexto(request))
            return vista(request, *args, **kwargs)
        return portales.portal_requerido(tipo)(envuelta)
    return decorador


# ---------------------------------------------------------------------------
# El calendario
# ---------------------------------------------------------------------------
def _datos_del_evento(evento, espacio, volver):
    """Lo que static/js/agenda.js muestra en la ventana del evento."""
    externo = getattr(evento, 'es_externo', False)
    datos = {
        'id': str(evento.pk), 'titulo': evento.titulo, 'descripcion': evento.descripcion, 'descripcionHtml': str(reglas.descripcion_html(evento)),
        'alcance': evento.nombre_alcance, 'tipo': evento.nombre_tipo if evento.tipo else '', 'color': evento.color,
        'colorTexto': evento.color_texto, 'fechas': evento.texto_de_fechas, 'horario': evento.texto_de_horario, 'lugar': evento.lugar,
        'repeticion': getattr(evento, 'repeticion', ''), 'importante': evento.importante,
    }
    if externo:
        datos.update(navega=bool(evento.url_propia), detalle=evento.url_propia)
        return datos
    datos.update(detalle=_url_del_detalle(espacio, evento, volver), calendario=espacio.url('evento_ics', evento.pk))
    if espacio.vista.gestiona:
        consulta = urlencode({'volver': volver})
        datos.update(editar=f'{espacio.url("editar", evento.pk)}?{consulta}', eliminar=f'{espacio.url("eliminar", evento.pk)}?{consulta}',
                     duplicar=f'{espacio.url("crear")}?{urlencode({"copiar": evento.pk, "volver": volver})}')
    return datos


def _url_del_detalle(espacio, evento, volver):
    return f'{espacio.url("calendario")}?{urlencode({"evento": evento.pk, "volver": volver})}'


def _leyenda(opciones, eventos):
    """Los colores de los niveles (los que puede ver y el de todo el colegio) y de lo de otros módulos que aparece."""
    alcances = [clave for clave, _ in opciones[1:-1]] + [COLEGIO]
    leyenda = [(clave, NOMBRE_DE_ALCANCE[clave], *COLORES[clave]) for clave in alcances]
    presentes = {evento.fuente for evento in eventos if getattr(evento, 'es_externo', False)}
    return leyenda + [(fuente, *fuentes.LEYENDA[fuente]) for fuente in fuentes.LEYENDA if fuente in presentes]


def _por_inicio(eventos, desde, hasta):
    """[(fecha, [eventos])]: cada evento una vez, en su primer día dentro de las fechas (para la lista de próximos)."""
    dias = {}
    for evento in sorted(eventos, key=calendario._orden):
        if evento.fecha_fin < desde or evento.fecha_inicio > hasta:
            continue
        dias.setdefault(max(evento.fecha_inicio, desde), []).append(evento)
    return sorted(dias.items())


def _inicio_de_la_semana(lunes, domingo):
    """«12» (del 12 al 18 de octubre), «26 de octubre» (al 1 de noviembre) o «28 de diciembre de 2026» (al 3 de enero)."""
    if lunes.month == domingo.month:
        return str(lunes.day)
    return date_format(lunes, 'j \\d\\e F' if lunes.year == domingo.year else 'j \\d\\e F \\d\\e Y').lower()


def _calendario(request, espacio):
    if 'evento' in request.GET:
        return _detalle(request, espacio, request.GET['evento'])
    persona, vista = espacio.persona, espacio.vista
    recordatorios.generar_si_toca()
    recordatorios.marcar_vistos(persona)   # al abrir la agenda, sus recordatorios quedan vistos
    hoy = timezone.localdate()
    modo = request.GET.get('vista', 'mes')
    if modo not in dict(VISTAS):
        modo = 'mes'
    opciones = vista.opciones()
    filtro = request.GET.get('nivel', '')
    if filtro not in dict(opciones):
        filtro = ''
    tipo = request.GET.get('tipo', '')
    if tipo not in dict(TIPOS):
        tipo = ''
    texto = request.GET.get('q', '').strip()[:80]
    primero = calendario.primer_dia(request.GET.get('mes', ''), hoy)
    dia = parse_date(request.GET.get('dia', '') or '') or (hoy if primero == hoy.replace(day=1) else primero)
    lunes = dia - timedelta(days=dia.weekday())

    base = espacio.url('calendario')
    actuales = {'vista': modo if modo != 'mes' else '', 'mes': f'{primero:%Y-%m}' if modo == 'mes' else '',
                'dia': f'{lunes:%Y-%m-%d}' if modo == 'semana' else '', 'nivel': filtro, 'tipo': tipo}

    def enlace(**cambios):
        datos = {clave: valor for clave, valor in {**actuales, **cambios}.items() if valor}
        return f'{base}?{urlencode(datos)}' if datos else base

    contexto = {
        **espacio.extra, 'base': espacio.base, 'espacio': espacio.nombre, 'gestiona': vista.gestiona, 'hoy': hoy, 'modo': modo,
        'vistas': [(clave, nombre, enlace(vista=clave if clave != 'mes' else '', mes=f'{primero:%Y-%m}' if clave == 'mes' else '',
                                          dia=f'{lunes:%Y-%m-%d}' if clave == 'semana' else '')) for clave, nombre in VISTAS],
        'opciones': opciones, 'filtro': filtro, 'tipos': TIPOS, 'tipo': tipo, 'texto': texto, 'sin_niveles': not vista.todos and not vista.niveles,
        'url_calendario': base, 'url_crear': espacio.url('crear') if vista.gestiona else '', 'primero': primero, 'carriles': calendario.CARRILES,
        'url_suscripcion': espacio.url('suscripcion'),
        'url_imprimir': f'{espacio.url("imprimir")}?{urlencode({k: v for k, v in {"mes": f"{primero:%Y-%m}", "nivel": filtro, "tipo": tipo}.items() if v})}',
    }

    if texto:   # la búsqueda: un año atrás y uno adelante
        futuros, pasados = reglas.buscar(persona, texto, filtro, tipo)
        eventos = futuros + pasados
        volver = enlace(q=texto)
        contexto.update(futuros=futuros, pasados=pasados, encontrados=len(eventos), titulo=f'Resultados para «{texto}»')
    elif modo == 'semana':
        domingo = lunes + timedelta(days=6)
        eventos = reglas.eventos_de(persona, lunes, domingo, filtro, tipo)
        volver = enlace()
        por_dia = dict(reglas.por_dia(eventos, lunes, domingo))
        contexto.update(
            titulo=f'Semana del {_inicio_de_la_semana(lunes, domingo)} al {date_format(domingo, "j \\d\\e F \\d\\e Y").lower()}',
            dias_de_la_semana=[(lunes + timedelta(days=i), por_dia.get(lunes + timedelta(days=i), [])) for i in range(7)],
            anterior=enlace(dia=f'{lunes - timedelta(days=7):%Y-%m-%d}'), siguiente=enlace(dia=f'{lunes + timedelta(days=7):%Y-%m-%d}'),
            actual=enlace(dia=f'{hoy:%Y-%m-%d}'), es_actual=lunes <= hoy <= domingo, eventos_del_periodo=len(eventos))
    elif modo == 'lista':
        desde = parse_date(request.GET.get('desde', '') or '') or hoy
        hasta = desde + timedelta(days=DIAS_DE_LA_LISTA)
        eventos = reglas.eventos_de(persona, desde, hasta, filtro, tipo)
        volver = enlace()
        contexto.update(titulo='Próximos eventos', lista=_por_inicio(eventos, desde, hasta), desde=desde, hasta=hasta,
                        siguiente=enlace(desde=f'{hasta + timedelta(days=1):%Y-%m-%d}'), eventos_del_periodo=len(eventos),
                        actual=enlace(), es_actual=desde == hoy)
    else:
        desde, hasta = calendario.rango_visible(primero)
        eventos = reglas.eventos_de(persona, desde, hasta, filtro, tipo)
        volver = enlace()
        agenda = calendario.agenda_del_mes(eventos, primero)
        contexto.update(
            titulo=date_format(primero, 'F Y').capitalize(), semanas=calendario.semanas(eventos, primero, hoy), agenda=agenda,
            eventos_del_mes=sum(len(lista) for _, lista in agenda), anterior=enlace(mes=f'{calendario.mes_anterior(primero):%Y-%m}'),
            siguiente=enlace(mes=f'{calendario.mes_siguiente(primero):%Y-%m}'), actual=enlace(mes=f'{hoy:%Y-%m}'),
            es_actual=primero == hoy.replace(day=1))
    contexto.update(volver=volver, leyenda=_leyenda(opciones, eventos), datos_eventos=[_datos_del_evento(e, espacio, volver) for e in eventos])
    return render(request, 'agenda/calendario.html', contexto)


@login_required
@require_GET
def calendario_vista(request):
    return _calendario(request, _del_sistema(request))


@require_GET
def portal_calendario(request):
    return _calendario(request, request.espacio_agenda)


def _evento_visible(espacio, pk):
    if not str(pk).isdigit():
        raise Http404('No existe ese evento.')
    evento = get_object_or_404(EventoAgenda, pk=pk)
    if not espacio.vista.puede_ver(evento):
        raise Http404('No existe ese evento.')
    return evento


def _detalle(request, espacio, pk):
    evento = _evento_visible(espacio, pk)
    recordatorios.marcar_vistos(espacio.persona, evento)
    volver = request.GET.get('volver', '')
    if not (volver.startswith(espacio.url('calendario')) and '//' not in volver):
        volver = f'{espacio.url("calendario")}?mes={evento.fecha_inicio:%Y-%m}'
    de_la_serie = EventoAgenda.objects.filter(serie=evento.serie).count() if evento.serie else 0
    return render(request, 'agenda/detalle.html', {
        **espacio.extra, 'base': espacio.base, 'evento': evento, 'gestiona': espacio.vista.gestiona, 'volver': volver,
        'url_calendario': espacio.url('calendario'), 'descripcion': reglas.descripcion_html(evento),
        'url_ics': espacio.url('evento_ics', evento.pk), 'de_la_serie': de_la_serie,
    })


def _evento_ics(request, espacio, pk):
    """«Agregar a mi calendario»: el evento como archivo .ics."""
    evento = _evento_visible(espacio, pk)
    url = request.build_absolute_uri(f'{espacio.url("calendario")}?evento={evento.pk}')
    respuesta = HttpResponse(reglas.ics_de_evento(evento, url), content_type='text/calendar; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="evento-{evento.pk}.ics"'
    return respuesta


@login_required
@require_GET
def evento_ics(request, pk):
    return _evento_ics(request, _del_sistema(request), pk)


@require_GET
def portal_evento_ics(request, pk):
    return _evento_ics(request, request.espacio_agenda, pk)


# ---------------------------------------------------------------------------
# La suscripción del teléfono
# ---------------------------------------------------------------------------
def _suscripcion(request, espacio):
    """La página con su enlace secreto (se crea la primera vez) y cómo agregarlo; «Generar un enlace nuevo» lo cambia."""
    filtro = espacio.persona.filtro_de_persona
    if request.method == 'POST':
        SuscripcionCalendario.objects.filter(**filtro).delete()
        SuscripcionCalendario.objects.create(**filtro)
        messages.success(request, 'Se generó un enlace nuevo. El anterior ya no funciona: vuelve a suscribirte con este.')
        return redirect(espacio.url('suscripcion'))
    suscripcion = SuscripcionCalendario.objects.filter(**filtro).first() or SuscripcionCalendario.objects.create(**filtro)
    enlace = request.build_absolute_uri(reverse('agenda:suscripcion_ics', args=[suscripcion.token]))
    return render(request, 'agenda/suscripcion.html', {
        **espacio.extra, 'base': espacio.base, 'enlace': enlace, 'webcal': 'webcal://' + enlace.split('://', 1)[-1],
        'url_calendario': espacio.url('calendario'), 'suscripcion': suscripcion,
    })


@login_required
def suscripcion(request):
    return _suscripcion(request, _del_sistema(request))


def portal_suscripcion(request):
    return _suscripcion(request, request.espacio_agenda)


@require_GET
def suscripcion_ics(request, token):
    """El calendario de la persona del enlace (sin sesión: el calendario del teléfono no inicia sesión). Una cuenta que
    ya no está activa no recibe nada."""
    suscripcion = SuscripcionCalendario.objects.select_related('usuario', 'tutor', 'alumno').filter(token=token).first()
    if suscripcion is None:
        raise Http404('No existe ese calendario.')
    persona = Persona(usuario=suscripcion.usuario, tutor=suscripcion.tutor, alumno=suscripcion.alumno)
    if persona.usuario is not None and not persona.usuario.is_active:
        raise Http404('No existe ese calendario.')
    if persona.usuario is None and portales.motivo_sin_acceso(portales.TUTOR if persona.tutor else portales.ESTUDIANTE,
                                                              persona.tutor or persona.alumno):
        raise Http404('No existe ese calendario.')
    SuscripcionCalendario.objects.filter(pk=suscripcion.pk).update(usada_en=timezone.now())
    respuesta = HttpResponse(reglas.ics_de_suscripcion(persona, request.build_absolute_uri), content_type='text/calendar; charset=utf-8')
    respuesta['Cache-Control'] = 'private, max-age=1800'
    return respuesta


# ---------------------------------------------------------------------------
# Imprimir el mes
# ---------------------------------------------------------------------------
def _imprimir(request, espacio):
    """El mes en una hoja limpia (para el periódico mural o guardarla en PDF): todos los eventos de cada día, sin
    menús ni botones, con la leyenda de colores."""
    hoy = timezone.localdate()
    primero = calendario.primer_dia(request.GET.get('mes', ''), hoy)
    opciones = espacio.vista.opciones()
    filtro = request.GET.get('nivel', '') if request.GET.get('nivel', '') in dict(opciones) else ''
    tipo = request.GET.get('tipo', '') if request.GET.get('tipo', '') in dict(TIPOS) else ''
    desde, hasta = calendario.rango_visible(primero)
    eventos = reglas.eventos_de(espacio.persona, desde, hasta, filtro, tipo)
    por_dia = dict(reglas.por_dia(eventos, desde, hasta))
    semanas = []
    lunes = desde
    while lunes <= hasta:
        semanas.append([(lunes + timedelta(days=i), (lunes + timedelta(days=i)).month == primero.month,
                         por_dia.get(lunes + timedelta(days=i), [])) for i in range(7)])
        lunes += timedelta(days=7)
    return render(request, 'agenda/imprimir.html', {
        'primero': primero, 'semanas': semanas, 'leyenda': _leyenda(opciones, eventos), 'generado': timezone.localtime(),
        'filtro': dict(opciones).get(filtro, '') if filtro else '', 'tipo': NOMBRE_DE_TIPO.get(tipo, '') if tipo else '',
        'volver': f'{espacio.url("calendario")}?mes={primero:%Y-%m}',
    })


@login_required
@require_GET
def imprimir(request):
    return _imprimir(request, _del_sistema(request))


@require_GET
def portal_imprimir(request):
    return _imprimir(request, request.espacio_agenda)


# ---------------------------------------------------------------------------
# Registrar, editar, duplicar y eliminar (solo el administrador)
# ---------------------------------------------------------------------------
def _volver(request, evento=None):
    """A dónde regresar: el calendario de donde se abrió (mismo mes y nivel) o, si no, el mes del evento."""
    por_omision = reverse('agenda:calendario')
    if evento is not None:
        por_omision += f'?mes={evento.fecha_inicio:%Y-%m}'
    pedido = request.POST.get('volver') or request.GET.get('volver') or ''
    if pedido.startswith(reverse('agenda:calendario')) and '//' not in pedido:
        return pedido
    return por_omision


def _ir_al_mes(destino, evento):
    """El calendario de `destino` pero en el mes del evento (para verlo recién guardado), con el mismo nivel."""
    partes = urlsplit(destino)
    datos = dict(parse_qsl(partes.query))
    datos.pop('evento', None)
    if datos.get('vista') == 'semana':
        datos['dia'] = f'{evento.fecha_inicio:%Y-%m-%d}'
    elif datos.get('vista') != 'lista':
        datos['mes'] = f'{evento.fecha_inicio:%Y-%m}'
    return f'{partes.path}?{urlencode(datos)}'


@requiere_permisos(alcance.GESTIONAR)
def crear(request):
    inicial = {'todo_el_dia': True, 'saltar_sin_clases': True}
    original = None
    copiar = request.GET.get('copiar', '')
    if copiar.isdigit():   # «Duplicar»: empieza con lo de ese evento
        original = EventoAgenda.objects.filter(pk=copiar).first()
        if original is not None:
            inicial.update(reglas.valores_para_duplicar(original))
    fecha = request.GET.get('fecha', '')
    if fecha and original is None:
        inicial.update(fecha_inicio=fecha, fecha_fin=fecha)
    form = EventoForm(request.POST or None, initial=inicial)
    if request.method == 'POST' and form.is_valid():
        datos = form.cleaned_data
        creados = reglas.crear(form.save(commit=False), request.user, repetir=datos.get('repetir', ''), hasta=datos.get('repetir_hasta'),
                               saltar_sin_clases=datos.get('saltar_sin_clases', False))
        if len(creados) > 1:
            messages.success(request, f'Se registró «{creados[0].titulo}» en {len(creados)} fechas ({creados[0].repeticion}).')
        else:
            messages.success(request, f'Se registró el evento «{creados[0].titulo}».')
        return redirect(_ir_al_mes(_volver(request), creados[0]))
    return render(request, 'agenda/evento_form.html', {'form': form, 'volver': _volver(request), 'evento': None, 'original': original})


@requiere_permisos(alcance.GESTIONAR)
def editar(request, pk):
    evento = get_object_or_404(EventoAgenda, pk=pk)
    form = EventoForm(request.POST or None, instance=evento)
    if request.method == 'POST' and form.is_valid():
        otros = reglas.guardar_cambios(form.save(commit=False), request.user, toda_la_serie=form.cleaned_data.get('toda_la_serie', False))
        messages.success(request, f'Se guardaron los cambios de «{evento.titulo}»' + (f' y de {otros} evento{"s" if otros != 1 else ""} siguiente{"s" if otros != 1 else ""} de la serie.' if otros else '.'))
        return redirect(_ir_al_mes(_volver(request, evento), evento))
    return render(request, 'agenda/evento_form.html', {'form': form, 'volver': _volver(request, evento), 'evento': evento})


@requiere_permisos(alcance.GESTIONAR)
def eliminar(request, pk):
    evento = get_object_or_404(EventoAgenda, pk=pk)
    volver = _volver(request, evento)
    siguientes = reglas.siguientes_de_la_serie(evento).count() if evento.serie else 1
    if request.method == 'POST':
        titulo = evento.titulo
        total = reglas.eliminar(evento, request.user, y_siguientes=request.POST.get('alcance') == 'siguientes')
        messages.success(request, f'Se eliminó el evento «{titulo}».' if total == 1 else f'Se eliminaron {total} eventos de la serie «{titulo}».')
        return redirect(volver)
    return render(request, 'agenda/evento_eliminar.html', {'evento': evento, 'volver': volver, 'siguientes': siguientes})
