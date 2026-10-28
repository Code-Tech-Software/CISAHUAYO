"""Agenda / Calendario: el calendario mensual (en el sistema y en los portales), el detalle de un evento y su registro,
edición y eliminación (solo el administrador: Agenda.gestionar).

El calendario es la misma pantalla en el sistema y en los portales (`base` cambia); qué eventos ve cada quien lo decide
Agenda/alcance.py en el servidor. El mes (`mes=AAAA-MM`) y el nivel (`nivel=`) van en la dirección: al cambiar de mes
se conserva el nivel, y al guardar, editar o eliminar se vuelve al mismo mes y nivel. El detalle de un evento como
página (sin JavaScript o por un enlace directo) es la misma dirección con `evento=`: consultar la agenda no pide
permiso (cada quien ve lo suyo), así que no hay otra ruta que proteger.
"""
from dataclasses import dataclass, field
from functools import wraps
from urllib.parse import parse_qsl, urlencode, urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from CISAHUAYO import portales
from CISAHUAYO.permisos import requiere_permisos

from . import alcance, calendario
from .comunicados import COLOR as COLOR_DE_COMUNICADO
from .comunicados import COLOR_TEXTO as COLOR_TEXTO_DE_COMUNICADO
from .comunicados import EventoDeComunicado, eventos_de_comunicados
from .forms import EventoForm
from .models import COLEGIO, COLORES, NOMBRE_DE_ALCANCE, EventoAgenda

ESPACIO_DE_PORTAL = {portales.TUTOR: 'portal_tutores:agenda', portales.ESTUDIANTE: 'portal_estudiantes:agenda'}


@dataclass
class Espacio:
    vista: alcance.Vista
    base: str = 'base.html'
    nombre: str = 'agenda'              # espacio de nombres de las direcciones
    extra: dict = field(default_factory=dict)

    def url(self, nombre, *args):
        return reverse(f'{self.nombre}:{nombre}', args=args)


def _del_sistema(request):
    return Espacio(vista=alcance.de_usuario(request.user))


def para_portal(tipo):
    """Una vista de la agenda para las cuentas de un portal (su sesión: CISAHUAYO/portales.py)."""
    def decorador(vista):
        @wraps(vista)
        def envuelta(request, *args, **kwargs):
            cuenta = request.cuenta_portal
            vista_ = alcance.de_tutor(cuenta) if tipo == portales.TUTOR else alcance.de_estudiante(cuenta)
            request.espacio_agenda = Espacio(vista=vista_, base='portales/base.html', nombre=ESPACIO_DE_PORTAL[tipo],
                                             extra=portales.contexto(request))
            return vista(request, *args, **kwargs)
        return portales.portal_requerido(tipo)(envuelta)
    return decorador


# ---------------------------------------------------------------------------
# El calendario
# ---------------------------------------------------------------------------
def _datos_del_evento(evento, espacio, volver):
    datos = {
        'id': evento.pk, 'titulo': evento.titulo, 'descripcion': evento.descripcion, 'alcance': evento.nombre_alcance,
        'color': evento.color, 'colorTexto': evento.color_texto, 'fechas': evento.texto_de_fechas,
        'horario': evento.texto_de_horario, 'lugar': evento.lugar, 'detalle': _url_del_detalle(espacio, evento, volver),
    }
    if espacio.vista.gestiona:
        consulta = urlencode({'volver': volver})
        datos.update(editar=f'{espacio.url("editar", evento.pk)}?{consulta}', eliminar=f'{espacio.url("eliminar", evento.pk)}?{consulta}')
    return datos


def _url_del_detalle(espacio, evento, volver):
    return f'{espacio.url("calendario")}?{urlencode({"evento": evento.pk, "volver": volver})}'


def _calendario(request, espacio):
    if 'evento' in request.GET:
        return _detalle(request, espacio, request.GET['evento'])
    hoy = timezone.localdate()
    primero = calendario.primer_dia(request.GET.get('mes', ''), hoy)
    vista = espacio.vista
    opciones = vista.opciones()
    filtro = request.GET.get('nivel', '')
    if filtro not in dict(opciones):
        filtro = ''
    desde, hasta = calendario.rango_visible(primero)
    eventos = list(vista.filtrar(vista.eventos(), filtro).filter(fecha_inicio__lte=hasta, fecha_fin__gte=desde))
    # Los comunicados con evento de quien mira (no son de un nivel: solo sin filtro de nivel)
    de_comunicados = [] if filtro else eventos_de_comunicados(request, desde, hasta)
    eventos += de_comunicados

    base = espacio.url('calendario')
    def enlace(mes, **extra):
        datos = {'mes': f'{mes:%Y-%m}', **({'nivel': filtro} if filtro else {}), **extra}
        return f'{base}?{urlencode(datos)}'
    volver = enlace(primero)
    alcances = [clave for clave, _ in opciones[1:-1]] + [COLEGIO]
    agenda = calendario.agenda_del_mes(eventos, primero)
    return render(request, 'agenda/calendario.html', {
        **espacio.extra, 'base': espacio.base, 'espacio': espacio.nombre, 'gestiona': vista.gestiona,
        'primero': primero, 'hoy': hoy, 'semanas': calendario.semanas(eventos, primero, hoy), 'carriles': calendario.CARRILES,
        'agenda': agenda, 'eventos_del_mes': sum(len(lista) for _, lista in agenda),
        'opciones': opciones, 'filtro': filtro, 'sin_niveles': not vista.todos and not vista.niveles,
        'leyenda': [(clave, NOMBRE_DE_ALCANCE[clave], *COLORES[clave]) for clave in alcances]
                   + ([('COMUNICADO', 'Comunicados', COLOR_DE_COMUNICADO, COLOR_TEXTO_DE_COMUNICADO)] if de_comunicados else []),
        'anterior': enlace(calendario.mes_anterior(primero)), 'siguiente': enlace(calendario.mes_siguiente(primero)),
        'actual': enlace(hoy.replace(day=1)), 'es_mes_actual': primero == hoy.replace(day=1), 'volver': volver,
        'url_calendario': base, 'url_crear': espacio.url('crear') if vista.gestiona else '',
        'datos_eventos': [e.como_dato() if isinstance(e, EventoDeComunicado) else _datos_del_evento(e, espacio, volver) for e in eventos],
    })


@login_required
@require_GET
def calendario_vista(request):
    return _calendario(request, _del_sistema(request))


@require_GET
def portal_calendario(request):
    return _calendario(request, request.espacio_agenda)


def _detalle(request, espacio, pk):
    if not str(pk).isdigit():
        raise Http404('No existe ese evento.')
    evento = get_object_or_404(EventoAgenda, pk=pk)
    if not espacio.vista.puede_ver(evento):
        raise Http404('No existe ese evento.')
    volver = request.GET.get('volver', '')
    if not (volver.startswith(espacio.url('calendario')) and '//' not in volver):
        volver = f'{espacio.url("calendario")}?mes={evento.fecha_inicio:%Y-%m}'
    return render(request, 'agenda/detalle.html', {
        **espacio.extra, 'base': espacio.base, 'evento': evento, 'gestiona': espacio.vista.gestiona, 'volver': volver,
        'url_calendario': espacio.url('calendario'),
    })


# ---------------------------------------------------------------------------
# Registrar, editar y eliminar (solo el administrador)
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
    datos['mes'] = f'{evento.fecha_inicio:%Y-%m}'
    return f'{partes.path}?{urlencode(datos)}'


@requiere_permisos(alcance.GESTIONAR)
def crear(request):
    inicial = {'todo_el_dia': True}
    fecha = request.GET.get('fecha', '')
    if fecha:
        inicial.update(fecha_inicio=fecha, fecha_fin=fecha)
    form = EventoForm(request.POST or None, initial=inicial)
    if request.method == 'POST' and form.is_valid():
        evento = form.save(commit=False)
        evento.creado_por = evento.modificado_por = request.user
        evento.save()
        messages.success(request, f'Se registró el evento «{evento.titulo}».')
        return redirect(_ir_al_mes(_volver(request), evento))
    return render(request, 'agenda/evento_form.html', {'form': form, 'volver': _volver(request), 'evento': None})


@requiere_permisos(alcance.GESTIONAR)
def editar(request, pk):
    evento = get_object_or_404(EventoAgenda, pk=pk)
    form = EventoForm(request.POST or None, instance=evento)
    if request.method == 'POST' and form.is_valid():
        evento = form.save(commit=False)
        evento.modificado_por = request.user
        evento.save()
        messages.success(request, f'Se guardaron los cambios de «{evento.titulo}».')
        return redirect(_ir_al_mes(_volver(request, evento), evento))
    return render(request, 'agenda/evento_form.html', {'form': form, 'volver': _volver(request, evento), 'evento': evento})


@requiere_permisos(alcance.GESTIONAR)
def eliminar(request, pk):
    evento = get_object_or_404(EventoAgenda, pk=pk)
    volver = _volver(request, evento)
    if request.method == 'POST':
        titulo = evento.titulo
        evento.delete()
        messages.success(request, f'Se eliminó el evento «{titulo}».')
        return redirect(volver)
    return render(request, 'agenda/evento_eliminar.html', {'evento': evento, 'volver': volver})
