"""Agenda / Calendario: el calendario (por mes, por semana, la lista de próximos o el ciclo escolar completo, con
búsqueda), el detalle de un evento, sus archivos, su archivo de calendario, la suscripción del teléfono, la vista para
imprimir y el registro, la edición, la cancelación y la eliminación (el administrador, Agenda.gestionar; o quien gestiona
sus niveles, Agenda.gestionar_nivel), también de los eventos que se repiten y al duplicar uno.

El calendario es la misma pantalla en el sistema y en los portales (`base` cambia); qué eventos ve cada quien lo decide
Agenda/alcance.py en el servidor, y lo de otros módulos (días sin clases, comunicados, reuniones, fechas de
calificaciones y ciclo escolar) Agenda/fuentes.py. El mes (`mes=AAAA-MM`), la semana (`dia=AAAA-MM-DD`), la lista
(`desde=`), el nivel (`nivel=`), el grado o grupo (`curso=g12` o `r34`), el tipo (`tipo=`), la vista (`vista=`) y la
búsqueda (`q=`) van en la dirección; una fecha imposible se ignora (no es un error). El detalle de un evento como página
es la misma dirección con `evento=`: consultar la agenda no pide permiso (cada quien ve lo suyo).
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import wraps
from urllib.parse import parse_qsl, urlencode, urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.formats import date_format
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO import portales
from CISAHUAYO.permisos import requiere_alguno

from . import alcance, calendario, fuentes, recordatorios, reglas
from .forms import CancelarForm, EventoForm
from .fuentes import Persona
from .models import COLEGIO, COLORES, NOMBRE_DE_ALCANCE, NOMBRE_DE_TIPO, TIPOS, VACACIONES, VARIOS, AdjuntoEvento, EventoAgenda, SuscripcionCalendario

ESPACIO_DE_PORTAL = {portales.TUTOR: 'portal_tutores:agenda', portales.ESTUDIANTE: 'portal_estudiantes:agenda'}
VISTAS = (('mes', 'Mes'), ('semana', 'Semana'), ('lista', 'Próximos'), ('ciclo', 'Ciclo escolar'))
TIPOS_DEL_FILTRO = [*TIPOS, (reglas.OTRO, 'Otros')]
DIAS_DE_LA_LISTA = 60
GESTIONAR = (alcance.GESTIONAR, alcance.GESTIONAR_NIVEL)


@dataclass
class Espacio:
    persona: Persona
    base: str = 'base.html'
    nombre: str = 'agenda'              # espacio de nombres de las direcciones
    extra: dict = field(default_factory=dict)

    @property
    def vista(self):
        return self.persona.vista

    @property
    def del_sistema(self):
        return self.persona.usuario is not None

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


def _fecha(texto):
    """La fecha de la dirección («2026-11-04»), o None si no es una fecha posible (2026-02-31, año 9999…)."""
    try:
        fecha = parse_date(str(texto or ''))
    except ValueError:
        return None
    return fecha if fecha is not None and 1900 <= fecha.year <= 2200 else None


def _numero(texto):
    """El número de la dirección (solo cifras 0-9), o None."""
    texto = str(texto or '')
    return int(texto) if re.fullmatch(r'[0-9]{1,12}', texto) else None


# ---------------------------------------------------------------------------
# El calendario
# ---------------------------------------------------------------------------
def _url_del_evento(evento, espacio, volver):
    """A dónde lleva un evento sin JavaScript (o abierto en otra pestaña): su página, la de su módulo o, si es de otro
    módulo sin página propia (un día sin clases, una fecha de calificaciones), el mes en que ocurre."""
    if getattr(evento, 'es_externo', False):
        return evento.url_propia or f'{espacio.url("calendario")}?mes={evento.fecha_inicio:%Y-%m}'
    return f'{espacio.url("calendario")}?{urlencode({"evento": evento.pk, "volver": volver})}'


def _datos_del_evento(evento, espacio, volver):
    """Lo que static/js/agenda.js muestra en la ventana del evento."""
    externo = getattr(evento, 'es_externo', False)
    datos = {
        'id': str(evento.pk), 'titulo': evento.titulo, 'descripcion': evento.descripcion, 'descripcionHtml': str(reglas.descripcion_html(evento)),
        'alcance': evento.nombre_alcance, 'tipo': evento.nombre_tipo if evento.tipo else '', 'color': evento.color,
        'colorTexto': evento.color_texto, 'fechas': evento.texto_de_fechas, 'horario': evento.texto_de_horario, 'lugar': evento.lugar,
        'repeticion': getattr(evento, 'repeticion', ''), 'importante': evento.importante,
        'cancelado': evento.cancelado, 'motivo': getattr(evento, 'motivo_cancelacion', ''),
    }
    if externo:
        datos.update(navega=bool(evento.url_propia), detalle=evento.url_propia)
        return datos
    detalle = _url_del_evento(evento, espacio, volver)
    datos.update(detalle=detalle, calendario=espacio.url('evento_ics', evento.pk), publico=reglas.texto_de_publico(evento) if espacio.del_sistema else '',
                 adjuntos=[{'nombre': a.nombre_original, 'url': espacio.url('adjunto', a.pk)} for a in evento.adjuntos.all()],
                 confirmar=detalle if evento.pide_confirmacion and espacio.vista.publico == alcance.FAMILIAS and reglas.puede_confirmar(evento) else '')
    if espacio.vista.puede_gestionar(evento):
        consulta = urlencode({'volver': volver})
        datos.update(editar=f'{espacio.url("editar", evento.pk)}?{consulta}', eliminar=f'{espacio.url("eliminar", evento.pk)}?{consulta}',
                     duplicar=f'{espacio.url("crear")}?{urlencode({"copiar": evento.pk, "volver": volver})}', resumen=detalle)
        if evento.cancelado:
            datos['reactivar'] = f'{espacio.url("reactivar", evento.pk)}?{consulta}'
        else:
            datos['cancelar'] = f'{espacio.url("cancelar", evento.pk)}?{consulta}'
    return datos


def _leyenda(opciones, eventos):
    """Los colores de los niveles (los que puede ver, el de varios niveles si aparece y el de todo el colegio) y de lo de
    otros módulos que aparece."""
    alcances = [clave for clave, _ in opciones[1:-1]] + ([VARIOS] if any(getattr(e, 'alcance', '') == VARIOS for e in eventos) else []) + [COLEGIO]
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


def _ciclo_para(fecha):
    """El ciclo escolar que contiene esa fecha; si ninguno, el actual."""
    from Alumnos.models import CicloEscolar
    return (CicloEscolar.objects.filter(fecha_inicio__lte=fecha, fecha_fin__gte=fecha).order_by('-activo', '-fecha_inicio').first()
            or CicloEscolar.objects.filter(activo=True).first())


def _aviso_sin_niveles(espacio):
    vista = espacio.vista
    if vista.todos or vista.niveles:
        return ''
    if vista.publico == alcance.FAMILIAS:
        return 'Tus estudiantes no tienen inscripción en el ciclo actual: ves los eventos de todo el colegio.'
    if vista.publico == alcance.ESTUDIANTES:
        return 'No tienes inscripción en el ciclo actual: ves los eventos de todo el colegio.'
    return 'Tu cuenta no tiene niveles educativos asignados: ves los eventos de todo el colegio.'


def _calendario(request, espacio):
    if 'evento' in request.GET:
        return _detalle(request, espacio, request.GET['evento'])
    persona, vista = espacio.persona, espacio.vista
    recordatorios.generar_si_toca()
    recordatorios.marcar_vistos(persona)   # al abrir la agenda, sus avisos quedan vistos
    hoy = timezone.localdate()
    modo = request.GET.get('vista', 'mes')
    if modo not in dict(VISTAS):
        modo = 'mes'
    opciones = vista.opciones()
    filtro = request.GET.get('nivel', '')
    if filtro not in dict(opciones):
        filtro = ''
    cursos = vista.cursos()
    curso = request.GET.get('curso', '')
    grado, grupo = vista.curso_pedido(curso) if curso else (None, None)
    if grado is None:
        curso = ''
    tipo = request.GET.get('tipo', '')
    if tipo not in dict(TIPOS_DEL_FILTRO):
        tipo = ''
    texto = request.GET.get('q', '').strip()[:80]
    dia = _fecha(request.GET.get('dia'))
    if 'mes' in request.GET or dia is None:
        primero = calendario.primer_dia(request.GET.get('mes', ''), hoy)
        dia = dia or (hoy if primero == hoy.replace(day=1) else primero)
    else:
        primero = dia.replace(day=1)       # desde una semana: su mes (al cambiar a Mes o al imprimir)
    lunes = dia - timedelta(days=dia.weekday())
    desde_lista = _fecha(request.GET.get('desde')) or hoy

    base = espacio.url('calendario')
    actuales = {'vista': modo if modo != 'mes' else '', 'mes': f'{primero:%Y-%m}' if modo == 'mes' else '',
                'dia': f'{lunes:%Y-%m-%d}' if modo in ('semana', 'ciclo') else '', 'desde': f'{desde_lista:%Y-%m-%d}' if modo == 'lista' and desde_lista != hoy else '',
                'nivel': filtro, 'curso': curso, 'tipo': tipo}

    def enlace(**cambios):
        datos = {clave: valor for clave, valor in {**actuales, **cambios}.items() if valor}
        return f'{base}?{urlencode(datos)}' if datos else base

    def a_la_vista(clave):
        return enlace(vista=clave if clave != 'mes' else '', mes=f'{primero:%Y-%m}' if clave == 'mes' else '',
                      dia=f'{lunes:%Y-%m-%d}' if clave in ('semana', 'ciclo') else '', desde='')

    filtro_de_otros = grado.nivel if grado is not None else filtro
    contexto = {
        **espacio.extra, 'base': espacio.base, 'espacio': espacio.nombre, 'gestiona': vista.gestiona, 'hoy': hoy, 'modo': modo,
        'vistas': [(clave, nombre, a_la_vista(clave)) for clave, nombre in VISTAS],
        'opciones': opciones, 'filtro': filtro, 'cursos': cursos, 'curso': curso, 'tipos': TIPOS_DEL_FILTRO, 'tipo': tipo, 'texto': texto,
        'aviso_sin_niveles': _aviso_sin_niveles(espacio), 'url_calendario': base, 'url_crear': espacio.url('crear') if vista.gestiona else '',
        'primero': primero, 'dia': dia, 'lunes': lunes, 'desde': desde_lista, 'url_suscripcion': espacio.url('suscripcion'),
        'consulta_filtros': urlencode({clave: valor for clave, valor in (('nivel', filtro), ('curso', curso), ('tipo', tipo)) if valor}),
    }
    impresion = {'mes': f'{primero:%Y-%m}', 'nivel': filtro, 'curso': curso, 'tipo': tipo}

    if texto:   # la búsqueda: un año atrás y uno adelante
        futuros, pasados = reglas.buscar(persona, texto, filtro, tipo, (grado, grupo))
        eventos = futuros + pasados
        volver = enlace(q=texto)
        contexto.update(futuros=futuros, pasados=pasados, encontrados=len(eventos), titulo=f'Resultados para «{texto}»')
    elif modo == 'semana':
        domingo = lunes + timedelta(days=6)
        eventos = reglas.eventos_de(persona, lunes, domingo, filtro, tipo, (grado, grupo))
        volver = enlace()
        sin_clases = reglas.dias_sin_clases_de(persona, lunes, domingo, filtro_de_otros)
        por_dia = dict(reglas.por_dia(eventos, lunes, domingo))
        contexto.update(
            titulo=f'Semana del {_inicio_de_la_semana(lunes, domingo)} al {date_format(domingo, "j \\d\\e F \\d\\e Y").lower()}',
            semana=calendario.semana_en_columnas(eventos, lunes, hoy, sin_clases),
            dias_de_la_semana=[(lunes + timedelta(days=i), por_dia.get(lunes + timedelta(days=i), [])) for i in range(7)],
            anterior=enlace(dia=f'{lunes - timedelta(days=7):%Y-%m-%d}'), siguiente=enlace(dia=f'{lunes + timedelta(days=7):%Y-%m-%d}'),
            actual=enlace(dia=f'{hoy:%Y-%m-%d}'), es_actual=lunes <= hoy <= domingo, eventos_del_periodo=len(eventos))
    elif modo == 'lista':
        hasta = desde_lista + timedelta(days=DIAS_DE_LA_LISTA)
        eventos = reglas.eventos_de(persona, desde_lista, hasta, filtro, tipo, (grado, grupo))
        volver = enlace()
        contexto.update(titulo='Próximos eventos', lista=_por_inicio(eventos, desde_lista, hasta), hasta=hasta,
                        siguiente=enlace(desde=f'{hasta + timedelta(days=1):%Y-%m-%d}'), eventos_del_periodo=len(eventos),
                        actual=enlace(desde=''), es_actual=desde_lista == hoy)
    elif modo == 'ciclo':
        ciclo = _ciclo_para(dia)
        inicio, fin = (ciclo.fecha_inicio, ciclo.fecha_fin) if ciclo else (primero, calendario.mes_siguiente(primero) + timedelta(days=330))
        eventos = reglas.eventos_de(persona, inicio, fin, filtro, tipo, (grado, grupo))
        volver = enlace()
        sin_clases = reglas.dias_sin_clases_de(persona, inicio, fin, filtro_de_otros)
        contexto.update(titulo=f'Ciclo escolar {ciclo.nombre}' if ciclo else 'Ciclo escolar', ciclo=ciclo,
                        meses=calendario.meses_del_ciclo(inicio, fin, eventos, hoy, sin_clases),
                        anterior=enlace(dia=f'{inicio - timedelta(days=1):%Y-%m-%d}') if ciclo else '',
                        siguiente=enlace(dia=f'{fin + timedelta(days=1):%Y-%m-%d}') if ciclo else '',
                        actual=enlace(dia=''), es_actual=ciclo is not None and inicio <= hoy <= fin)
        impresion = {'vista': 'ciclo', 'dia': f'{dia:%Y-%m-%d}', 'nivel': filtro, 'curso': curso, 'tipo': tipo}
    else:
        desde, hasta = calendario.rango_visible(primero)
        eventos = reglas.eventos_de(persona, desde, hasta, filtro, tipo, (grado, grupo))
        volver = enlace()
        sin_clases = reglas.dias_sin_clases_de(persona, desde, hasta, filtro_de_otros)
        agenda = calendario.agenda_del_mes(eventos, primero)
        contexto.update(
            titulo=date_format(primero, 'F Y').capitalize(), semanas=calendario.semanas(eventos, primero, hoy, sin_clases=sin_clases),
            mini=calendario.mini_mes(primero, eventos, hoy, sin_clases), agenda=agenda, eventos_del_mes=sum(len(lista) for _, lista in agenda),
            anterior=enlace(mes=f'{calendario.mes_anterior(primero):%Y-%m}'), siguiente=enlace(mes=f'{calendario.mes_siguiente(primero):%Y-%m}'),
            actual=enlace(mes=f'{hoy:%Y-%m}'), es_actual=primero == hoy.replace(day=1))
    contexto.update(volver=volver, leyenda=_leyenda(opciones, eventos), datos_eventos=[_datos_del_evento(e, espacio, volver) for e in eventos],
                    url_imprimir=f'{espacio.url("imprimir")}?{urlencode({k: v for k, v in impresion.items() if v})}')
    for evento in eventos:   # a dónde lleva cada evento sin JavaScript (templates/agenda/_tarjeta.html)
        evento.url_en_agenda = _url_del_evento(evento, espacio, volver)
    return render(request, 'agenda/calendario.html', contexto)


@login_required
@require_GET
def calendario_vista(request):
    return _calendario(request, _del_sistema(request))


@require_GET
def portal_calendario(request):
    return _calendario(request, request.espacio_agenda)


def _evento_visible(espacio, pk):
    numero = _numero(pk)
    if numero is None:
        raise Http404('No existe ese evento.')
    evento = get_object_or_404(EventoAgenda.objects.prefetch_related('niveles_varios'), pk=numero)
    if not espacio.vista.puede_ver(evento):
        raise Http404('No existe ese evento.')
    return evento


def _volver_del_detalle(request, espacio, evento):
    volver = request.GET.get('volver', '') or request.POST.get('volver', '')
    if not (volver.startswith(espacio.url('calendario')) and '//' not in volver):
        volver = f'{espacio.url("calendario")}?mes={evento.fecha_inicio:%Y-%m}'
    return volver


def _enlaces_de_otros_modulos(request, espacio, evento):
    """«Avisar con un comunicado» (si puede enviar comunicados) y «Registrar en Asistencia» (un evento de vacaciones, si
    puede registrar días sin clases): abren esos formularios ya llenos; se confirma allá."""
    usuario = request.user
    if not espacio.del_sistema:
        return {}
    enlaces = {}
    if usuario.has_perm('Comunicados.enviar') and evento.comunicado_id is None and not evento.cancelado:
        enlaces['url_comunicado'] = f'{reverse("comunicados:crear")}?{urlencode({"desde_agenda": evento.pk})}'
    if evento.tipo == VACACIONES and usuario.has_perm('Alumnos.add_dianolectivo') and not evento.cancelado:
        datos = {'sin_clases_desde': f'{evento.fecha_inicio:%Y-%m-%d}', 'sin_clases_motivo': evento.titulo[:120]}
        if evento.varios_dias:
            datos['sin_clases_hasta'] = f'{evento.fecha_fin:%Y-%m-%d}'
        niveles = ['TODOS'] if evento.alcance == COLEGIO else evento.niveles_del_evento
        enlaces['url_sin_clases'] = f'{reverse("ciclos:dias_sin_clases")}?{urlencode(datos)}&' + '&'.join(f'sin_clases_niveles={n}' for n in niveles)
    if evento.comunicado_id and (usuario.has_perm('Comunicados.seguimiento') or evento.comunicado.autor_id == usuario.pk):
        enlaces['url_comunicado_enviado'] = reverse('comunicados:detalle', args=[evento.comunicado_id])
    return enlaces


def _detalle(request, espacio, pk):
    evento = _evento_visible(espacio, pk)
    recordatorios.marcar_vistos(espacio.persona, evento)
    volver = _volver_del_detalle(request, espacio, evento)
    de_la_serie = EventoAgenda.objects.filter(serie=evento.serie).count() if evento.serie else 0
    vista = espacio.vista
    gestiona = vista.puede_gestionar(evento)
    contexto = {
        **espacio.extra, 'base': espacio.base, 'evento': evento, 'gestiona': gestiona, 'volver': volver,
        'url_calendario': espacio.url('calendario'), 'descripcion': reglas.descripcion_html(evento),
        'url_ics': espacio.url('evento_ics', evento.pk), 'de_la_serie': de_la_serie, 'espacio': espacio.nombre,
        'adjuntos': [(a, espacio.url('adjunto', a.pk)) for a in evento.adjuntos.all()],
        'publico': reglas.texto_de_publico(evento) if espacio.del_sistema else '',
        **_enlaces_de_otros_modulos(request, espacio, evento),
    }
    if evento.pide_confirmacion and vista.publico == alcance.FAMILIAS:
        tutor = espacio.persona.tutor
        contexto.update(puede_confirmar=reglas.puede_confirmar(evento), url_confirmar=espacio.url('confirmar', evento.pk),
                        mi_confirmacion=evento.confirmaciones.filter(tutor=tutor).first(),
                        personas_posibles=range(1, 11))
    if evento.pide_confirmacion and gestiona:
        contexto['confirmaciones'] = reglas.resumen_de_confirmaciones(evento)
    return render(request, 'agenda/detalle.html', contexto)


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


def _adjunto(request, espacio, pk):
    """Un archivo del evento, solo para quien ve el evento (sin mostrar dónde está guardado)."""
    from Conducta.views import entregar_archivo
    adjunto = get_object_or_404(AdjuntoEvento.objects.select_related('evento'), pk=pk)
    if not espacio.vista.puede_ver(adjunto.evento):
        raise Http404('No existe ese archivo.')
    return entregar_archivo(adjunto.archivo, adjunto.nombre_original, adjunto.tipo, descargar=request.GET.get('descargar') == '1')


@login_required
@require_GET
def adjunto(request, pk):
    return _adjunto(request, _del_sistema(request), pk)


@require_GET
def portal_adjunto(request, pk):
    return _adjunto(request, request.espacio_agenda, pk)


@require_POST
def portal_confirmar(request, pk):
    """«¿Asistirán?» de una familia (solo en el portal de tutores, hasta que el evento empiece)."""
    espacio = request.espacio_agenda
    evento = _evento_visible(espacio, pk)
    if espacio.vista.publico != alcance.FAMILIAS or not reglas.puede_confirmar(evento):
        messages.error(request, 'Este evento ya no recibe confirmaciones.')
    else:
        asistira = request.POST.get('asistira') == 'si'
        reglas.confirmar(evento, espacio.persona.tutor, asistira, _numero(request.POST.get('personas')) or 1)
        messages.success(request, 'Gracias: se guardó que asistirán.' if asistira else 'Gracias: se guardó que no asistirán.')
    return redirect(f'{espacio.url("calendario")}?{urlencode({"evento": evento.pk, "volver": _volver_del_detalle(request, espacio, evento)})}')


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
# Imprimir el mes o el ciclo escolar
# ---------------------------------------------------------------------------
def _imprimir(request, espacio):
    """El mes en una hoja limpia (para el periódico mural o guardarla en PDF): todos los eventos de cada día, sin
    menús ni botones, con la leyenda de colores. Con `vista=ciclo`, todo el ciclo escolar en miniatura."""
    hoy = timezone.localdate()
    vista = espacio.vista
    opciones = vista.opciones()
    filtro = request.GET.get('nivel', '') if request.GET.get('nivel', '') in dict(opciones) else ''
    tipo = request.GET.get('tipo', '') if request.GET.get('tipo', '') in dict(TIPOS_DEL_FILTRO) else ''
    grado, grupo = vista.curso_pedido(request.GET.get('curso')) if request.GET.get('curso') else (None, None)
    filtro_de_otros = grado.nivel if grado is not None else filtro
    textos = {'filtro': dict(opciones).get(filtro, '') if filtro else '', 'tipo': dict(TIPOS_DEL_FILTRO).get(tipo, '') if tipo else '',
              'curso': str(grupo or grado or ''), 'generado': timezone.localtime()}
    if request.GET.get('vista') == 'ciclo':
        dia = _fecha(request.GET.get('dia')) or hoy
        ciclo = _ciclo_para(dia)
        if ciclo is None:
            raise Http404('No hay ciclo escolar.')
        eventos = reglas.eventos_de(espacio.persona, ciclo.fecha_inicio, ciclo.fecha_fin, filtro, tipo, (grado, grupo))
        sin_clases = reglas.dias_sin_clases_de(espacio.persona, ciclo.fecha_inicio, ciclo.fecha_fin, filtro_de_otros)
        return render(request, 'agenda/imprimir_ciclo.html', {
            **textos, 'ciclo': ciclo, 'leyenda': _leyenda(opciones, eventos),
            'meses': calendario.meses_del_ciclo(ciclo.fecha_inicio, ciclo.fecha_fin, eventos, hoy, sin_clases),
            'volver': f'{espacio.url("calendario")}?vista=ciclo&dia={dia:%Y-%m-%d}',
        })
    primero = calendario.primer_dia(request.GET.get('mes', ''), hoy)
    desde, hasta = calendario.rango_visible(primero)
    eventos = reglas.eventos_de(espacio.persona, desde, hasta, filtro, tipo, (grado, grupo))
    sin_clases = reglas.dias_sin_clases_de(espacio.persona, desde, hasta, filtro_de_otros)
    por_dia = dict(reglas.por_dia(eventos, desde, hasta))
    semanas = []
    lunes = desde
    while lunes <= hasta:
        semanas.append([(lunes + timedelta(days=i), (lunes + timedelta(days=i)).month == primero.month,
                         por_dia.get(lunes + timedelta(days=i), []), sin_clases.get(lunes + timedelta(days=i), '')) for i in range(7)])
        lunes += timedelta(days=7)
    return render(request, 'agenda/imprimir.html', {
        **textos, 'primero': primero, 'semanas': semanas, 'leyenda': _leyenda(opciones, eventos),
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
# Registrar, editar, duplicar, cancelar y eliminar (el administrador, o quien gestiona sus niveles)
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
    if datos.get('vista') in ('semana', 'ciclo'):
        datos['dia'] = f'{evento.fecha_inicio:%Y-%m-%d}'
    elif datos.get('vista') != 'lista':
        datos['mes'] = f'{evento.fecha_inicio:%Y-%m}'
    return f'{partes.path}?{urlencode(datos)}'


def _gestionable(request, pk):
    """El evento, si quien lo pide puede gestionarlo (el administrador, o uno solo de sus niveles); si no, 403."""
    evento = get_object_or_404(EventoAgenda.objects.prefetch_related('niveles_varios'), pk=pk)
    if not alcance.de_usuario(request.user).puede_gestionar(evento):
        raise PermissionDenied('Ese evento no es de los niveles que gestionas.')
    return evento


def _formulario(request, form, evento=None, original=None):
    return render(request, 'agenda/evento_form.html', {
        'form': form, 'volver': _volver(request, evento), 'evento': evento, 'original': original,
        'acepta': '.jpg,.jpeg,.png,.webp,.pdf', 'maximo_adjuntos': EventoAgenda.MAXIMO_ADJUNTOS,
    })


@requiere_alguno(*GESTIONAR)
def crear(request):
    vista = alcance.de_usuario(request.user)
    inicial = {'todo_el_dia': True, 'saltar_sin_clases': True}
    if not vista.gestiona_todo and len(vista.niveles_que_gestiona) == 1:
        inicial['alcance'] = vista.niveles_que_gestiona
    original = None
    copiar = _numero(request.GET.get('copiar'))
    if copiar is not None:   # «Duplicar»: empieza con lo de ese evento (si puede gestionarlo)
        original = EventoAgenda.objects.prefetch_related('niveles_varios').filter(pk=copiar).first()
        if original is not None and vista.puede_gestionar(original):
            inicial.update(reglas.valores_para_duplicar(original))
        else:
            original = None
    fecha = _fecha(request.GET.get('fecha'))
    if fecha and original is None:
        inicial.update(fecha_inicio=f'{fecha:%Y-%m-%d}', fecha_fin=f'{fecha:%Y-%m-%d}')
    form = EventoForm(request.POST or None, initial=inicial, vista=vista, archivos=request.FILES.getlist('archivos'))
    if request.method == 'POST' and form.is_valid():
        datos = form.cleaned_data
        creados = reglas.crear(form.save(commit=False), request.user, repetir=datos.get('repetir', ''), hasta=datos.get('repetir_hasta'),
                               saltar_sin_clases=datos.get('saltar_sin_clases', False), destino=form.destino, archivos=form.archivos_validos)
        if len(creados) > 1:
            messages.success(request, f'Se registró «{creados[0].titulo}» en {len(creados)} fechas ({creados[0].repeticion}).')
        else:
            messages.success(request, f'Se registró el evento «{creados[0].titulo}».')
        return redirect(_ir_al_mes(_volver(request), creados[0]))
    return _formulario(request, form, original=original)


@requiere_alguno(*GESTIONAR)
def editar(request, pk):
    evento = _gestionable(request, pk)
    vista = alcance.de_usuario(request.user)
    form = EventoForm(request.POST or None, instance=evento, vista=vista, archivos=request.FILES.getlist('archivos'))
    if request.method == 'POST' and form.is_valid():
        datos = form.cleaned_data
        otros = reglas.guardar_cambios(form.save(commit=False), request.user, toda_la_serie=datos.get('toda_la_serie', False),
                                       destino=form.destino, archivos=form.archivos_validos, quitar=form.quitar_adjuntos(),
                                       avisar=datos.get('avisar_cambio', False))
        messages.success(request, f'Se guardaron los cambios de «{evento.titulo}»' + (f' y de {otros} evento{"s" if otros != 1 else ""} siguiente{"s" if otros != 1 else ""} de la serie.' if otros else '.'))
        return redirect(_ir_al_mes(_volver(request, evento), evento))
    return _formulario(request, form, evento=evento)


@requiere_alguno(*GESTIONAR)
def cancelar(request, pk):
    """Cancelar sin borrar: sigue en la agenda, tachado, con su motivo; se avisa a quienes lo ven."""
    evento = _gestionable(request, pk)
    volver = _volver(request, evento)
    siguientes = reglas.siguientes_de_la_serie(evento).filter(cancelado_en__isnull=True).count() if evento.serie else 1
    form = CancelarForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        total = reglas.cancelar(evento, request.user, form.cleaned_data['motivo'], y_siguientes=request.POST.get('alcance') == 'siguientes',
                                avisar=form.cleaned_data['avisar'])
        messages.success(request, f'Se canceló «{evento.titulo}».' if total == 1 else f'Se cancelaron {total} eventos de la serie «{evento.titulo}».')
        return redirect(volver)
    return render(request, 'agenda/evento_cancelar.html', {'evento': evento, 'volver': volver, 'siguientes': siguientes, 'form': form})


@require_POST
@requiere_alguno(*GESTIONAR)
def reactivar(request, pk):
    evento = _gestionable(request, pk)
    reglas.reactivar(evento, request.user)
    messages.success(request, f'«{evento.titulo}» vuelve a estar activo.')
    return redirect(_volver(request, evento))


@requiere_alguno(*GESTIONAR)
def eliminar(request, pk):
    evento = _gestionable(request, pk)
    volver = _volver(request, evento)
    siguientes = reglas.siguientes_de_la_serie(evento).count() if evento.serie else 1
    if request.method == 'POST':
        titulo = evento.titulo
        total = reglas.eliminar(evento, request.user, y_siguientes=request.POST.get('alcance') == 'siguientes')
        messages.success(request, f'Se eliminó el evento «{titulo}».' if total == 1 else f'Se eliminaron {total} eventos de la serie «{titulo}».')
        return redirect(volver)
    return render(request, 'agenda/evento_eliminar.html', {'evento': evento, 'volver': volver, 'siguientes': siguientes})
