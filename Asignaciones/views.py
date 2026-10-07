"""Quién imparte qué: el tablero de asignaciones, la carga de cada profesor y la bitácora de movimientos.

Las asignaciones en sí viven en `MateriaGrado.profesor` y se cambian con `Profesores.views.asignar` (una o varias a la
vez); aquí se consultan, se reparten en bloque (pasar las clases de un profesor a otro) y se exportan.
"""
import csv

from django.contrib import messages
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from Alumnos.academico import ciclo_editable, elegir_ciclo
from Alumnos.docentes import (
    asignaciones_vigentes,
    asignar_profesor,
    carga_de_profesores,
    con_habilitados,
    descripcion_del_cambio,
    resumen_del_ciclo,
)
from Alumnos.horarios import con_resumen_de_horario
from Alumnos.models import CicloEscolar, MateriaGrado, Profesor, orden_de_nivel
from Alumnos.utils import proteger_celda_csv
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, paginar
from CISAHUAYO.permisos import requiere_permisos
from CISAHUAYO.redireccion import destino_seguro, solo_numeros
from Usuarios.seguridad import ACCION_CAMBIO, registrar

from .forms import FiltroAsignacionesForm, FiltroCargaForm

POR_PAGINA_TABLERO = 50


def _ciclo_de(request):
    """Ciclo que se consulta: ?ciclo=, si no el actual y, si no hay, el más reciente."""
    ciclos = list(CicloEscolar.objects.all())
    return ciclos, elegir_ciclo(request.GET.get('ciclo', ''), ciclos)


def _asignaciones_filtradas(filtro, ciclo):
    """Las asignaciones vigentes del ciclo que cumplen los filtros, en orden escolar."""
    consulta = asignaciones_vigentes(ciclo) if ciclo else MateriaGrado.objects.none()
    return (
        filtro.filtrar(consulta)
        .select_related('grado', 'materia', 'profesor').prefetch_related('horarios')
        .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'materia__nombre')
    )


# ---------------------------------------------------------------------------
# Tablero
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_materiagrado')
def tablero(request):
    ciclos, ciclo = _ciclo_de(request)
    filtro = FiltroAsignacionesForm(request.GET)
    pagina, rango_paginas, por_pagina = paginar(request, _asignaciones_filtradas(filtro, ciclo), por_defecto=POR_PAGINA_TABLERO)
    filas = con_habilitados(con_resumen_de_horario(pagina.object_list))
    editable = ciclo_editable(ciclo)

    return render(request, 'asignaciones/tablero.html', {
        'ciclos': ciclos,
        'ciclo': ciclo,
        'editable': editable,
        'filtro': filtro,
        'filtros_activos': filtro.activos,
        'pagina': pagina,
        'filas': filas,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_TABLERO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'resumen': resumen_del_ciclo(ciclo),
        'profesores_activos': list(Profesor.objects.filter(estatus='ACTIVO')) if editable else [],
        'seccion': 'tablero',
    })


# ---------------------------------------------------------------------------
# Carga por profesor
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_materiagrado', 'Alumnos.view_profesor')
def carga(request):
    ciclos, ciclo = _ciclo_de(request)
    filtro = FiltroCargaForm(request.GET)

    # Los profesores activos y, aunque estén de baja, los que todavía imparten algo en el ciclo
    profesores = Profesor.objects.filter(Q(estatus='ACTIVO') | Q(asignaciones__ciclo=ciclo, asignaciones__activa=True)).distinct() if ciclo else Profesor.objects.none()
    todas = carga_de_profesores(ciclo, profesores)
    cargas = filtro.filtrar(todas)

    conteos = {estado: sum(1 for c in todas if c['estado'] == estado) for estado in ('sobrecarga', 'completa', 'libre')}
    conteos['con_carga'] = sum(1 for c in todas if c['estado'] in ('normal', 'sin_limite'))
    de_baja_con_clases = [c for c in todas if c['profesor'].estatus != 'ACTIVO' and c['total_materias']]
    editable = ciclo_editable(ciclo)

    return render(request, 'asignaciones/carga.html', {
        'ciclos': ciclos,
        'ciclo': ciclo,
        'editable': editable,
        'filtro': filtro,
        'filtros_activos': {k: v for k, v in filtro.activos.items() if k != 'orden'},
        'cargas': cargas,
        'total': len(todas),
        'conteos': conteos,
        'de_baja_con_clases': de_baja_con_clases,
        'profesores_activos': list(Profesor.objects.filter(estatus='ACTIVO')) if editable else [],
        'seccion': 'carga',
    })


# ---------------------------------------------------------------------------
# Pasar las clases de un profesor a otro
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.change_materiagrado')
def transferir(request):
    """Pasa todas las materias que un profesor imparte en un ciclo a otro profesor (o las deja sin profesor).

    Sirve cuando alguien se va o se ausenta. Se respeta lo de siempre: ciclo cerrado y empalmes de horario; lo que no se
    puede pasar se omite, se avisa y se queda con quien estaba.
    """
    ciclo = CicloEscolar.objects.filter(pk=request.POST.get('ciclo')).first() if request.POST.get('ciclo', '').isdigit() else None
    destino_url = destino_seguro(request, f'{reverse("asignaciones:carga")}{f"?ciclo={ciclo.pk}" if ciclo else ""}')
    origen = Profesor.objects.filter(pk=request.POST.get('origen')).first() if request.POST.get('origen', '').isdigit() else None
    if ciclo is None or origen is None:
        messages.error(request, 'No se encontró el ciclo o el profesor.')
        return redirect(destino_url)
    if not ciclo_editable(ciclo):
        messages.error(request, f'El ciclo {ciclo} está cerrado: sus asignaciones se conservan tal como quedaron.')
        return redirect(destino_url)

    valor = request.POST.get('destino', '')
    if valor == 'ninguno':
        profesor = None
    elif valor.isdigit() and int(valor) != origen.pk:
        profesor = Profesor.objects.filter(pk=valor, estatus='ACTIVO').first()
        if profesor is None:
            messages.error(request, 'Elige un profesor activo.')
            return redirect(destino_url)
    else:
        messages.error(request, 'Elige a quién pasarle las materias.')
        return redirect(destino_url)

    asignaciones = list(
        asignaciones_vigentes(ciclo).filter(profesor=origen)
        .select_related('materia', 'grado', 'ciclo', 'profesor').prefetch_related('horarios')
    )
    if not asignaciones:
        messages.info(request, f'{origen} no imparte ninguna materia en el ciclo {ciclo}.')
        return redirect(destino_url)

    cambios, omitidas = asignar_profesor(asignaciones, profesor)
    for asignacion, anterior in cambios:
        registrar(request.user, asignacion, ACCION_CAMBIO, descripcion_del_cambio(asignacion, anterior))
    hechas = len(cambios)
    if hechas:
        plural = 's' if hechas != 1 else ''
        if profesor:
            messages.success(request, f'{hechas} materia{plural} de {origen} pasaron a {profesor}.' if hechas != 1 else f'1 materia de {origen} pasó a {profesor}.')
        else:
            messages.success(request, f'{hechas} materia{plural} de {origen} quedaron sin profesor.' if hechas != 1 else f'1 materia de {origen} quedó sin profesor.')
    for motivo in omitidas[:5]:
        messages.error(request, f'No se pudo pasar. {motivo}')
    if len(omitidas) > 5:
        messages.error(request, f'Y {len(omitidas) - 5} más con el mismo problema.')
    return redirect(destino_url)


# ---------------------------------------------------------------------------
# Movimientos (bitácora)
# ---------------------------------------------------------------------------
TIPOS_DE_MOVIMIENTO = (('', 'Todos'), ('asignaciones', 'Asignaciones'), ('habilitaciones', 'Habilitaciones'))


def _movimientos(tipo):
    """Cambios de profesor en las materias de los grados y altas o bajas de «puede impartir»."""
    asignaciones = Q(content_type=ContentType.objects.get_for_model(MateriaGrado))
    habilitaciones = Q(content_type=ContentType.objects.get_for_model(Profesor)) & (
        Q(change_message__startswith='Habilitado para impartir') | Q(change_message__startswith='Ya no está habilitado')
    )
    criterio = {'asignaciones': asignaciones, 'habilitaciones': habilitaciones}.get(tipo, asignaciones | habilitaciones)
    return LogEntry.objects.filter(criterio).select_related('user', 'content_type').order_by('-action_time', '-pk')


@requiere_permisos('Alumnos.view_materiagrado')
def movimientos(request):
    tipo = request.GET.get('tipo', '')
    if tipo not in dict(TIPOS_DE_MOVIMIENTO):
        tipo = ''
    pagina, rango_paginas, por_pagina = paginar(request, _movimientos(tipo))

    ct_profesor = ContentType.objects.get_for_model(Profesor)
    entradas = []
    for entrada in pagina:
        habilitacion = entrada.content_type_id == ct_profesor.pk
        entradas.append({
            'cuando': entrada.action_time,
            'quien': (entrada.user.get_full_name() or entrada.user.get_username()) if entrada.user_id else 'Sistema',
            'tipo': 'Habilitación' if habilitacion else 'Asignación',
            'texto': f'{entrada.object_repr}: {entrada.change_message}' if habilitacion else entrada.change_message,
        })

    return render(request, 'asignaciones/movimientos.html', {
        'pagina': pagina,
        'entradas': entradas,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'tipo': tipo,
        'tipos': TIPOS_DE_MOVIMIENTO,
        'seccion': 'movimientos',
    })


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@require_GET
@requiere_permisos('Alumnos.view_materiagrado')
def exportar(request):
    _, ciclo = _ciclo_de(request)
    filtro = FiltroAsignacionesForm(request.GET)
    filas = con_habilitados(con_resumen_de_horario(_asignaciones_filtradas(filtro, ciclo)))

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="asignaciones-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta.write('﻿')  # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    escritor.writerow(['Ciclo', 'Nivel', 'Grado', 'Materia', 'Clave', 'Profesor', 'Puede impartirla', 'Horario', 'Horas por semana'])
    for fila in filas:
        sin_profesor = fila.profesor_id is None
        escritor.writerow([proteger_celda_csv(valor) for valor in (
            ciclo.nombre,
            fila.grado.get_nivel_display(),
            str(fila.grado),
            fila.materia.nombre,
            fila.materia.clave,
            'Sin profesor' if sin_profesor else str(fila.profesor),
            '' if sin_profesor else ('Sí' if fila.profesor_habilitado else 'No'),
            ' | '.join(fila.lineas),
            fila.duracion,
        )])
    return respuesta
