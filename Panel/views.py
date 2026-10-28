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

from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, paginar
from CISAHUAYO.permisos import requiere_permisos

from . import academico, indicadores, seguimiento
from .filtros import CLAVES, NOMBRES_DE_NIVEL, filtros_de
from .forms import CriterioSeguimientoForm
from .models import PROPUESTOS, CriterioSeguimiento

SESION = 'panel:filtros'
ALERTAS_EN_EL_PANEL = 6   # las de mayor prioridad; la lista completa está en su propia página
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


def _atencion(filtros, p, datos):
    """El centro de atención: asuntos accionables, de mayor a menor prioridad, con su acceso."""
    items = []
    consulta = filtros.consulta()

    def agregar(prioridad, icono, motivo, cantidad, url, detalle=''):
        if cantidad:
            items.append({'prioridad': prioridad, 'icono': icono, 'motivo': motivo, 'cantidad': cantidad, 'url': url, 'detalle': detalle})

    hoy = datos.get('entrada_hoy') or {}
    if p['asistencia'] and filtros.hoy_en_ciclo:
        if hoy.get('aplica'):
            grado = f'&grado={filtros.grado.pk}' if filtros.grado else ''
            agregar('media', 'user-check', 'Estudiantes sin registro de entrada hoy', hoy.get('sin_registro'),
                    f'{reverse("asistencias:dia")}?estado=SIN_REGISTRO{grado}', 'Todavía sin entrada ni falta: no cuentan como faltas.')
        from Alumnos.asistencias import dias_pendientes_de_cierre
        pendientes = _seguro(dias_pendientes_de_cierre)
        if isinstance(pendientes, list):
            agregar('alta', 'calendar', 'Días de asistencia sin cerrar', len(pendientes), reverse('asistencias:inicio'),
                    'Al cerrarlos se generan las faltas de quien no registró entrada (todo el colegio).')
    if p['calificaciones'] and filtros.ciclo is not None:
        n = _seguro(academico.pendientes_de_periodos_terminados, filtros)
        if isinstance(n, int):
            agregar('alta', 'award', 'Materias sin cerrar calificaciones de periodos terminados', n, reverse('calificaciones:inicio'))
    retiros = datos.get('retiros') or {}
    if retiros and not retiros.get('error'):
        agregar('alta', 'log-out', 'Retiros de hoy pendientes de confirmar', retiros.get('pendientes'), f'{reverse("retiros:lista")}?vista=hoy')
        agregar('media', 'log-out', 'Retiros de días anteriores sin confirmar ni cancelar', retiros.get('atrasados'),
                f'{reverse("retiros:lista")}?vista=todos&estado=AVISADO')
    conducta = datos.get('conducta') or {}
    if conducta and not conducta.get('error'):
        agregar('alta', 'flag', 'Casos de conducta con revisión vencida', conducta.get('vencidos'),
                f'{reverse("conducta:lista")}?estado=vencidos&ciclo={filtros.ciclo.pk}')
        agregar('alta', 'flag', 'Suspensiones o medidas por aprobar', conducta.get('solicitudes'), reverse('conducta:solicitudes'))
    resumen = datos.get('resumen_alertas') or {}
    url = f'{reverse("panel:seguimiento")}?{consulta}'
    agregar('alta', 'triangle-alert', 'Estudiantes con alertas de prioridad alta', resumen.get('alta'), f'{url}&prioridad=alta' if consulta else f'{url}prioridad=alta')
    agregar('media', 'circle-alert', 'Estudiantes con alertas de prioridad media', resumen.get('media'), f'{url}&prioridad=media' if consulta else f'{url}prioridad=media')
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
                datos['resumen_alertas'] = seguimiento.resumen(lista)
                motivo, prioridad = request.GET.get('motivo', ''), request.GET.get('prioridad', '')
                filtradas = seguimiento.filtrar(lista, motivo, prioridad)
                datos.update(alertas=filtradas[:ALERTAS_EN_EL_PANEL], alertas_filtradas=len(filtradas), motivo=motivo, prioridad=prioridad)
            else:
                datos['alertas_error'] = True
            datos['periodos_de_seguimiento'] = [(NOMBRES_DE_NIVEL[n], ev) for n, ev in evaluaciones.items()]
        datos['actividad'] = _seguro(indicadores.actividad, request.user, filtros, p)
        datos['atencion'] = _atencion(filtros, p, datos)
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
