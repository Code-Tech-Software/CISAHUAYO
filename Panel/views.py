"""Panel de control del administrador (pedido del 2026-10-18).

- `inicio`: el panel. Cada bloque se muestra solo a quien tiene el permiso de su módulo (se revisa aquí, en el
  servidor) y, si su consulta falla, solo ese bloque avisa del error. Una cuenta sin ninguno de esos permisos ve el
  panel de siempre (saludo y accesos). Las cuentas de prefectura tienen su propio panel.
- Los filtros se conservan en la sesión: al volver al panel desde un detalle (o desde el menú) sigue el mismo alcance,
  hasta «Restablecer».
- `seguimiento`: la lista completa de estudiantes que requieren atención, con los mismos filtros.
- `criterios`: los umbrales de esas alertas por nivel (en Ajustes).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, paginar
from CISAHUAYO.permisos import requiere_permisos

from . import academico, indicadores, seguimiento
from .filtros import CLAVES, NOMBRES_DE_NIVEL, filtros_de
from .forms import CriterioSeguimientoForm
from .models import PROPUESTOS, CriterioSeguimiento

SESION = 'panel:filtros'
ALERTAS_EN_EL_PANEL = 5   # las de mayor prioridad; la lista completa está en su propia página
VER_CRITERIOS, CAMBIAR_CRITERIOS = 'Panel.view_criterioseguimiento', 'Panel.change_criterioseguimiento'


def permisos_de(usuario):
    """Qué bloques puede ver la cuenta (los permisos de cada módulo)."""
    from Bitacoras.alcance import puede_entrar
    from Calificaciones.reglas import ve_todas
    from Comunicados.alcance import ENVIAR, es_administrador
    from Conducta.permisos import VER
    from Retiros.alcance import usa_retiros
    estudiantes = usuario.has_perm('Alumnos.view_alumno')
    return {
        'estudiantes': estudiantes,
        'asistencia': usuario.has_perm('Alumnos.view_asistenciageneral'),
        'justificaciones': usuario.has_perm('Alumnos.view_justificacion'),
        'calificaciones': ve_todas(usuario),
        'conducta': usuario.has_perm(VER),
        'bitacoras': puede_entrar(usuario),
        'retiros': usa_retiros(usuario),
        'comunicados': es_administrador(usuario) or usuario.has_perm(ENVIAR),
        'registrar_conducta': usuario.has_perm('Conducta.add_registroconducta'),
        'criterios': usuario.has_perm(VER_CRITERIOS),
    }


def _filtros(request):
    """Los filtros de la dirección (y se guardan) o, sin ellos, los últimos guardados en la sesión."""
    if any(clave in request.GET for clave in CLAVES):
        datos = {clave: request.GET.get(clave, '') for clave in CLAVES if request.GET.get(clave)}
        request.session[SESION] = datos
    else:
        datos = request.session.get(SESION, {})
    return filtros_de(datos)


def _seguro(funcion, *args):
    try:
        return funcion(*args)
    except DatabaseError:
        return {'error': True}


def _alertas_prioritarias(filtros, p, datos):
    """Las alertas prioritarias (rediseño del 2026-11-12): asuntos que piden una acción, cada uno con su cantidad y su
    unidad dicha con palabras (días, actas, estudiantes, casos, retiros), de mayor a menor prioridad y con el acceso a
    donde se resuelven. Lo de hoy que no es un pendiente (quién aún no registra entrada) va en la franja «Hoy»."""
    items = []

    def agregar(prioridad, icono, area, cantidad, singular, plural, texto, url, detalle=''):
        if cantidad:
            items.append({'prioridad': prioridad, 'icono': icono, 'area': area, 'cantidad': cantidad, 'url': url, 'detalle': detalle,
                          'texto': f'{cantidad} {singular if cantidad == 1 else plural} {texto}'})

    if p['asistencia'] and filtros.hoy_en_ciclo:
        from Alumnos.asistencias import dias_pendientes_de_cierre
        pendientes = _seguro(dias_pendientes_de_cierre)
        if isinstance(pendientes, list) and pendientes:
            fechas = ', '.join(date_format(d, 'D j M') for d in pendientes[:4]) + ('…' if len(pendientes) > 4 else '')
            agregar('alta', 'calendar', 'Asistencia', len(pendientes), 'día', 'días', 'de asistencia sin cerrar', reverse('asistencias:inicio'),
                    f'{fechas}. Al cerrarlos se generan las faltas de quien no registró entrada (todo el colegio).')
    actas = datos.get('actas') or {}
    if actas and not actas.get('error'):
        agregar('alta', 'award', 'Calificaciones', actas['pendientes'], 'acta', 'actas', 'de periodos terminados sin cerrar',
                reverse('calificaciones:inicio'), ' · '.join(f'{periodo}: {n}' for periodo, n in actas['por_periodo']))
    resumen = datos.get('resumen_alertas') or {}
    agregar('alta', 'triangle-alert', 'Seguimiento', resumen.get('alta'), 'estudiante', 'estudiantes', 'con prioridad alta',
            f'{reverse("panel:seguimiento")}?{filtros.consulta(prioridad="alta")}',
            'Inasistencia y bajo rendimiento a la vez, faltas seguidas o muchas materias reprobadas.')
    conducta = datos.get('conducta') or {}
    if conducta and not conducta.get('error'):
        agregar('alta', 'flag', 'Conducta', conducta.get('vencidos'), 'caso', 'casos', 'de conducta con revisión vencida',
                f'{reverse("conducta:lista")}?estado=vencidos&ciclo={filtros.ciclo.pk}', 'La fecha de revisión ya pasó y el caso sigue abierto.')
        agregar('alta', 'flag', 'Conducta', conducta.get('solicitudes'), 'suspensión o medida', 'suspensiones o medidas', 'por aprobar',
                reverse('conducta:solicitudes'), 'Las resuelve la dirección del nivel del estudiante.')
    retiros = datos.get('retiros') or {}
    if retiros and not retiros.get('error'):
        pasadas = retiros.get('hora_pasada') or 0
        agregar('alta' if pasadas else 'media', 'log-out', 'Retiros', retiros.get('pendientes'), 'retiro', 'retiros', 'de hoy por confirmar',
                f'{reverse("retiros:lista")}?vista=hoy', f'{pasadas} con la hora ya pasada.' if pasadas else 'Ninguno con la hora pasada todavía.')
        agregar('media', 'log-out', 'Retiros', retiros.get('atrasados'), 'retiro', 'retiros', 'de días anteriores sin confirmar ni cancelar',
                f'{reverse("retiros:lista")}?vista=todos&estado=AVISADO')
    orden = {'alta': 0, 'media': 1, 'baja': 2}
    return sorted(items, key=lambda i: orden[i['prioridad']])


@login_required
def inicio(request):
    """El panel de control: cualquier cuenta con sesión; cada quien ve los bloques de lo que su rol permite (sin
    ninguno, el saludo y los accesos de siempre). Una cuenta de prefectura tiene su propio panel."""
    from CISAHUAYO.context_processors import _usa_prefectura
    if _usa_prefectura(request.user):
        return redirect('prefectura:inicio')
    if 'restablecer' in request.GET:
        request.session.pop(SESION, None)
        return redirect('inicio')
    from Ciclos.reglas import aviso_del_cambio_de_ciclo
    p = permisos_de(request.user)
    aviso_ciclo = _seguro(aviso_del_cambio_de_ciclo, request.user)
    aviso_ciclo = None if isinstance(aviso_ciclo, dict) and aviso_ciclo.get('error') else aviso_ciclo
    from Agenda.fuentes import Persona
    from Agenda.reglas import para_el_inicio
    agenda = para_el_inicio(Persona(usuario=request.user))   # «Próximos eventos» (2026-10-27)
    if not any(p[c] for c in ('estudiantes', 'asistencia', 'calificaciones', 'conducta', 'retiros', 'comunicados')):
        return render(request, 'index.html', {'aviso_ciclo': aviso_ciclo, **agenda})

    filtros = _filtros(request)
    datos = {'filtros': filtros, 'p': p, 'generado': timezone.localtime(), 'aviso_ciclo': aviso_ciclo}
    if filtros.ciclo is not None:
        evaluaciones = academico.evaluaciones(filtros) if p['calificaciones'] or p['asistencia'] else {}
        if p['estudiantes']:
            datos['estudiantes'] = _seguro(indicadores.estudiantes, filtros)
        if p['asistencia']:
            datos['entrada_hoy'] = _seguro(indicadores.entrada_del_dia, filtros, filtros.hoy) if filtros.hoy_en_ciclo else {'aplica': False, 'motivo': 'El ciclo elegido no es el actual'}
            datos['dia_anterior'] = _seguro(indicadores.dia_anterior_con_registros, filtros)
            datos['asistencia'] = _seguro(indicadores.asistencia_del_rango, filtros)
        if p['calificaciones']:
            datos['academico'] = _seguro(indicadores.academico_del_alcance, filtros, evaluaciones)
            datos['captura'] = _seguro(academico.avance_de_captura, filtros, evaluaciones)
            datos['actas'] = _seguro(academico.actas_de_periodos_terminados, filtros)
        if p['conducta']:
            datos['conducta'] = _seguro(indicadores.conducta, filtros)
        if p['bitacoras']:
            datos['bitacoras'] = _seguro(indicadores.bitacoras, request.user, filtros)
        if p['retiros'] and filtros.hoy_en_ciclo:
            datos['retiros'] = _seguro(indicadores.retiros, request.user, filtros)
        if p['comunicados']:
            datos['comunicados'] = _seguro(indicadores.comunicados, request.user, filtros)
        if p['estudiantes'] and (p['asistencia'] or p['calificaciones']):
            lista = _seguro(seguimiento.alertas, filtros, p['asistencia'], p['calificaciones'], evaluaciones)
            if isinstance(lista, list):
                resumen = seguimiento.resumen(lista)
                activos = (datos.get('estudiantes') or {}).get('total')
                criterios = CriterioSeguimiento.por_nivel()
                datos.update(porcentaje_seguimiento=round(resumen['total'] * 100 / activos, 1) if activos else None,
                             criterios_propuestos=any(criterios[n].es_propuesto for n in filtros.niveles_en_alcance))
                # Por motivo, como en la lista completa (cada barra abre esa lista ya filtrada)
                maximo = max(resumen['inasistencia'], resumen['rendimiento'], 1)
                datos.update(resumen_alertas=resumen, alertas=lista[:ALERTAS_EN_EL_PANEL], motivos_alertas=[
                    {'nombre': nombre, 'valor': resumen[motivo], 'ancho': indicadores._ancho(resumen[motivo], maximo),
                     'url': f'{reverse("panel:seguimiento")}?{filtros.consulta(motivo=motivo)}'} for nombre, motivo in (
                        ('Inasistencia', 'inasistencia'), ('Bajo rendimiento', 'rendimiento'), ('Ambos motivos', 'ambos'))])
            else:
                datos['alertas_error'] = True
            datos['periodos_de_seguimiento'] = [(NOMBRES_DE_NIVEL[n], ev) for n, ev in evaluaciones.items()]
        datos['actividad'] = _seguro(indicadores.actividad, request.user, filtros, p)
        datos['atencion'] = _alertas_prioritarias(filtros, p, datos)
    datos.update(motivos=seguimiento.MOTIVOS, prioridades=seguimiento.PRIORIDADES, **agenda)
    return render(request, 'panel/inicio.html', datos)


@requiere_permisos('Alumnos.view_alumno')
def estudiantes_en_seguimiento(request):
    p = permisos_de(request.user)
    filtros = _filtros(request)
    lista = seguimiento.alertas(filtros, p['asistencia'], p['calificaciones'])
    motivo, prioridad = request.GET.get('motivo', ''), request.GET.get('prioridad', '')
    filtradas = seguimiento.filtrar(lista, motivo, prioridad)
    pagina, rango, por_pagina = paginar(request, filtradas)
    return render(request, 'panel/seguimiento.html', {
        'filtros': filtros, 'p': p, 'resumen': seguimiento.resumen(lista), 'pagina': pagina, 'rango': rango,
        'por_pagina': por_pagina, 'opciones_por_pagina': OPCIONES_POR_PAGINA, 'motivo': motivo, 'prioridad': prioridad,
        'motivos': seguimiento.MOTIVOS, 'prioridades': seguimiento.PRIORIDADES, 'total_filtradas': len(filtradas),
        'periodos_de_seguimiento': [(NOMBRES_DE_NIVEL[n], ev) for n, ev in academico.evaluaciones(filtros).items()],
    })


@requiere_permisos(VER_CRITERIOS)
def criterios(request):
    from Conducta.permisos import puede_configurar
    from .filtros import niveles_configurados
    niveles = niveles_configurados()
    actuales = CriterioSeguimiento.por_nivel()
    puede_cambiar = request.user.has_perm(CAMBIAR_CRITERIOS)
    datos = request.POST if request.method == 'POST' and puede_cambiar else None
    formularios = [(clave, nombre, CriterioSeguimientoForm(datos, instance=actuales[clave], prefix=clave.lower())) for clave, nombre in niveles]
    if datos is not None:
        if all(f.is_valid() for _, _, f in formularios):
            with transaction.atomic():
                for clave, _, form in formularios:
                    criterio = form.save(commit=False)
                    criterio.nivel, criterio.modificado_por = clave, request.user
                    criterio.save()
            messages.success(request, 'Se guardaron los criterios de seguimiento.')
            return redirect('panel:criterios')
        messages.error(request, 'Revisa los valores marcados.')
    return render(request, 'panel/criterios.html', {
        'formularios': formularios, 'puede_cambiar': puede_cambiar, 'propuestos': PROPUESTOS,
        'ajustes_seccion': 'seguimiento', 'puede_configurar_conducta': puede_configurar(request.user),
    })
