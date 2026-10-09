import csv
from collections import defaultdict
from itertools import groupby

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, IntegerField, Q, Value
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from Alumnos.academico import ciclo_actual, ciclo_editable, elegir_ciclo
from Alumnos.docentes import asignar_profesor, deshabilitar, descripcion_del_cambio, habilitar
from Alumnos.horarios import (
    con_resumen_de_horario,
    cuadricula,
    formatear_duracion,
    minutos_por_profesor,
    minutos_semanales,
)
from Alumnos.models import CicloEscolar, Materia, MateriaGrado, Profesor, ProfesorMateria, orden_de_nivel
from Alumnos.utils import ESTADOS_MX, proteger_celda_csv
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_permisos
from CISAHUAYO.redireccion import destino_seguro, solo_numeros
from Usuarios.docentes import desvincular, puede_desactivar_su_cuenta
from Usuarios.seguridad import ACCION_ALTA, ACCION_BAJA, ACCION_CAMBIO, puede_gestionar, registrar, rol_de
from Usuarios.views import SESION_CREDENCIALES, guardar_credenciales

from .forms import FiltroProfesoresForm, ProfesorForm


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_profesor')
def profesor_lista(request):
    filtro = FiltroProfesoresForm(request.GET)
    ciclo = ciclo_actual()
    profesores = filtro.filtrar(Profesor.objects.all(), ciclo).select_related('usuario').prefetch_related('niveles')
    if ciclo:
        profesores = profesores.annotate(
            materias=Count('asignaciones', filter=Q(asignaciones__ciclo=ciclo, asignaciones__activa=True), distinct=True),
        )
    else:
        profesores = profesores.annotate(materias=Value(0, output_field=IntegerField()))
    pagina, rango_paginas, por_pagina = paginar(request, profesores)

    # La carga horaria solo se calcula para los profesores de la página
    minutos = minutos_por_profesor([p.pk for p in pagina], ciclo)
    for profesor in pagina:
        profesor.duracion = formatear_duracion(minutos[profesor.pk]) if minutos[profesor.pk] else ''
        # Para la baja desde el listado: si se puede desactivar también su cuenta (lo mismo que ofrece su perfil)
        profesor.puede_desactivar_cuenta = profesor.estatus == 'ACTIVO' and puede_desactivar_su_cuenta(request.user, profesor)

    conteos = dict(Profesor.objects.order_by().values_list('estatus').annotate(total=Count('pk')))
    return render(request, 'profesores/lista.html', {
        'filtro': filtro,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'total_activos': conteos.get('ACTIVO', 0),
        'total_bajas': conteos.get('INACTIVO', 0),
        'viendo_bajas': filtro.activos.get('estatus') == 'INACTIVO',
        'filtros_activos': {k: v for k, v in filtro.activos.items() if k not in ('orden', 'estatus')},
        'ciclo': ciclo,
        # Tras darle acceso a un profesor se muestran, una sola vez, las credenciales de su cuenta
        'credenciales': request.session.pop(SESION_CREDENCIALES, None),
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, profesor=None):
    return render(request, 'profesores/form.html', {
        'form': form,
        'profesor': profesor,
        'es_edicion': profesor is not None,
        'estados_mx': ESTADOS_MX,
    })


def _resultado_del_acceso(request, form, profesor):
    """Si el formulario creó o vinculó la cuenta del profesor: bitácora, credenciales (una sola vez) y el texto del aviso."""
    cuenta = form.cuenta
    if cuenta is None:
        return ''
    if form.cuenta_nueva:
        registrar(request.user, cuenta, ACCION_ALTA, f'Cuenta creada con el rol «{rol_de(cuenta)}» para el profesor {profesor}.')
        registrar(request.user, profesor, ACCION_CAMBIO, f'Se le dio acceso al sistema con la cuenta «{cuenta.username}».')
        guardar_credenciales(request, cuenta, form.contrasena_en_claro, 'Acceso al sistema', url=profesor.get_absolute_url(),
                             escrita=form.acceso.contrasena_escrita, pedir_cambio=form.acceso.pedir_cambio)
        return f' Se creó su cuenta «{cuenta.username}» con el rol «{rol_de(cuenta)}».'
    registrar(request.user, cuenta, ACCION_CAMBIO, f'Se vinculó con la ficha del profesor {profesor}.')
    registrar(request.user, profesor, ACCION_CAMBIO, f'Se vinculó con la cuenta de acceso «{cuenta.username}».')
    return f' Ahora entra con la cuenta «{cuenta.username}».'


@requiere_permisos('Alumnos.add_profesor')
def profesor_crear(request):
    form = ProfesorForm(request.POST if request.method == 'POST' else None, actor=request.user,
                        abrir_acceso=request.GET.get('acceso') == '1')
    if request.method == 'POST':
        if form.is_valid():
            profesor = form.save()
            aviso = _resultado_del_acceso(request, form, profesor)
            messages.success(request, f'{profesor} fue registrado correctamente.{aviso}')
            return redirect('profesores:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@requiere_permisos('Alumnos.change_profesor')
def profesor_editar(request, pk):
    profesor = get_object_or_404(Profesor, pk=pk)
    form = ProfesorForm(request.POST if request.method == 'POST' else None, instance=profesor, actor=request.user,
                        abrir_acceso=request.GET.get('acceso') == '1')
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            aviso = _resultado_del_acceso(request, form, profesor)
            messages.success(request, f'Los datos de {profesor} se actualizaron.{aviso}')
            return redirect('profesores:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, profesor)


@require_POST
@requiere_permisos('Alumnos.change_profesor', 'auth.change_user')
def profesor_desvincular(request, pk):
    """Separa la ficha del profesor de su cuenta. No borra ni desactiva nada (sirve para corregir una vinculación equivocada)."""
    profesor = get_object_or_404(Profesor.objects.select_related('usuario'), pk=pk)
    if profesor.usuario_id is None:
        messages.info(request, f'{profesor} no tiene cuenta de acceso.')
        return redirect(profesor.get_absolute_url())
    if not puede_gestionar(request.user, profesor.usuario):
        raise PermissionDenied('No puedes administrar a un usuario con más permisos que tú.')
    cuenta = desvincular(profesor)
    registrar(request.user, profesor, ACCION_CAMBIO, f'Se desvinculó de la cuenta de acceso «{cuenta.username}».')
    registrar(request.user, cuenta, ACCION_CAMBIO, f'Se desvinculó de la ficha del profesor {profesor}.')
    messages.success(
        request,
        f'{profesor} ya no está vinculado con la cuenta «{cuenta.username}». La cuenta sigue existiendo: desactívala en «Usuarios» si ya no se usará.',
    )
    return redirect(profesor.get_absolute_url())


# ---------------------------------------------------------------------------
# Perfil: materias que imparte y su horario semanal (por ciclo)
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_profesor')
def profesor_detalle(request, pk):
    profesor = get_object_or_404(Profesor, pk=pk)
    ciclos = list(CicloEscolar.objects.all())
    ciclo = elegir_ciclo(request.GET.get('ciclo', ''), ciclos)

    asignaciones = []
    if ciclo:
        asignaciones = con_resumen_de_horario(
            MateriaGrado.objects.filter(profesor=profesor, ciclo=ciclo, activa=True)
            .select_related('materia', 'grado').prefetch_related('horarios')
            .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'materia__nombre')
        )
    # Cada bloque ya trae su asignación (con materia y grado) gracias al prefetch: sin consultas por celda
    bloques = [bloque for asignacion in asignaciones for bloque in asignacion.horarios.all()]
    minutos = minutos_semanales(bloques)
    editable = ciclo_editable(ciclo) and profesor.estatus == 'ACTIVO'

    # Materias del ciclo que todavía no tienen profesor, de los niveles en los que da clases: de ahí se le asignan
    pendientes = []
    if ciclo and editable:
        sin_profesor = (
            MateriaGrado.objects.filter(ciclo=ciclo, activa=True, profesor__isnull=True, materia__activa=True, grado__activo=True)
            .filter(grado__nivel__in=profesor.niveles.values('nivel'))
            .select_related('materia', 'grado').order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'materia__nombre')
        )
        pendientes = [
            {'grado': grado, 'asignaciones': list(grupo)}
            for grado, grupo in groupby(sin_profesor, key=lambda asignacion: asignacion.grado)
        ]

    # Habilitación: las materias que puede impartir, y cuáles da de hecho en el ciclo consultado
    habilitaciones = list(ProfesorMateria.objects.filter(profesor=profesor).select_related('materia').order_by('materia__nombre'))
    imparte = defaultdict(list)
    for asignacion in asignaciones:
        imparte[asignacion.materia_id].append(asignacion.grado)
    habilitadas = [
        {'materia': h.materia, 'grados': imparte.get(h.materia_id, [])} for h in habilitaciones
    ]
    ids_habilitadas = {h.materia_id for h in habilitaciones}
    sin_habilitar = [m for m in {a.materia_id: a.materia for a in asignaciones}.values() if m.pk not in ids_habilitadas]
    por_habilitar = (
        list(Materia.objects.filter(activa=True).exclude(pk__in=ids_habilitadas).order_by('nombre'))
        if request.user.has_perm('Alumnos.change_profesor') and profesor.estatus == 'ACTIVO' else []
    )

    # Su cuenta de acceso (una sola) y lo que quien consulta puede hacer con ella
    cuenta = profesor.usuario if profesor.usuario_id else None
    usuario = request.user
    puede_dar_acceso = (
        cuenta is None and profesor.estatus == 'ACTIVO' and usuario.has_perm('Alumnos.change_profesor')
        and (usuario.has_perm('auth.add_user') or usuario.has_perm('auth.change_user'))
    )

    return render(request, 'profesores/detalle.html', {
        'profesor': profesor,
        'cuenta': cuenta,
        'rol_cuenta': rol_de(cuenta) if cuenta else None,
        'puede_dar_acceso': puede_dar_acceso,
        'puede_desvincular': (
            cuenta is not None and usuario.has_perm('Alumnos.change_profesor') and usuario.has_perm('auth.change_user')
            and puede_gestionar(usuario, cuenta)
        ),
        'puede_desactivar_cuenta': puede_desactivar_su_cuenta(usuario, profesor),
        'habilitadas': habilitadas,
        'sin_habilitar': sin_habilitar,
        'materias_por_habilitar': por_habilitar,
        'ciclos': ciclos,
        'ciclo': ciclo,
        'asignaciones': asignaciones,
        'total_grados': len({a.grado_id for a in asignaciones}),
        'total_bloques': len(bloques),
        'horas_semanales': formatear_duracion(minutos) if minutos else '',
        'cuadricula': cuadricula(bloques),
        'editable': editable,
        'ciclo_abierto': ciclo_editable(ciclo),
        'pendientes': pendientes,
        'total_pendientes': sum(len(g['asignaciones']) for g in pendientes),
        'asignaciones_actuales': (
            MateriaGrado.objects.filter(profesor=profesor, ciclo__activo=True, activa=True).count()
            if profesor.estatus == 'ACTIVO' else 0
        ),
        'esta_de_baja': profesor.estatus == 'INACTIVO',
    })


# ---------------------------------------------------------------------------
# Baja lógica
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.delete_profesor')
def profesor_baja(request, pk):
    """Baja lógica: el profesor deja de ofrecerse al asignar materias, pero conserva su historial."""
    profesor = get_object_or_404(Profesor, pk=pk)
    if profesor.estatus == 'INACTIVO':
        messages.info(request, f'{profesor} ya estaba dado de baja.')
        return redirect('profesores:lista')

    liberadas = 0
    cuenta_desactivada = None
    with transaction.atomic():
        profesor.estatus = 'INACTIVO'
        profesor.save(update_fields=['estatus', 'modificado'])
        if request.POST.get('quitar_del_ciclo'):
            # Solo el ciclo actual: el historial de los ciclos cerrados conserva quién daba cada materia
            liberadas = MateriaGrado.objects.filter(profesor=profesor, ciclo__activo=True, activa=True).update(profesor=None)
        if request.POST.get('desactivar_cuenta') and puede_desactivar_su_cuenta(request.user, profesor):
            cuenta_desactivada = profesor.usuario
            cuenta_desactivada.is_active = False
            cuenta_desactivada.save(update_fields=['is_active'])
            registrar(request.user, cuenta_desactivada, ACCION_BAJA, f'Cuenta desactivada al dar de baja al profesor {profesor}.')

    aviso = f' Sus {liberadas} materia{"s" if liberadas != 1 else ""} del ciclo actual quedaron sin profesor.' if liberadas else ''
    if cuenta_desactivada:
        aviso += f' Su cuenta «{cuenta_desactivada.username}» quedó desactivada.'
    messages.success(
        request,
        f'{profesor} fue dado de baja.{aviso} Su registro se conserva y puedes reactivarlo desde el filtro «Bajas».',
    )
    return redirect('profesores:lista')


@require_POST
@requiere_permisos('Alumnos.change_profesor')
def profesor_reactivar(request, pk):
    profesor = get_object_or_404(Profesor, pk=pk)
    if profesor.estatus == 'INACTIVO':
        profesor.estatus = 'ACTIVO'
        profesor.save(update_fields=['estatus', 'modificado'])
        aviso = ''
        if profesor.usuario_id and not profesor.usuario.is_active:
            aviso = f' Su cuenta «{profesor.usuario.username}» sigue desactivada: reactívala en «Usuarios» si volverá a entrar al sistema.'
        messages.success(request, f'{profesor} fue reactivado. Asígnale de nuevo las materias que imparte.{aviso}')
    return redirect('profesores:lista')


# ---------------------------------------------------------------------------
# Habilitación: qué materias puede impartir el profesor (independiente del ciclo)
# ---------------------------------------------------------------------------
def _volver_al_perfil(request, profesor):
    return redirect(destino_seguro(request, f'{profesor.get_absolute_url()}#habilitado'))


@require_POST
@requiere_permisos('Alumnos.change_profesor')
def profesor_habilitar(request, pk):
    """Agrega materias a las que el profesor puede impartir. Sirve para sugerirlo al asignar; no asigna nada."""
    profesor = get_object_or_404(Profesor, pk=pk)
    if profesor.estatus == 'INACTIVO':
        messages.error(request, f'{profesor} está dado de baja. Reactívalo antes de cambiar sus materias.')
        return _volver_al_perfil(request, profesor)

    materias = list(Materia.objects.filter(pk__in=solo_numeros(request.POST.getlist('materia')), activa=True))
    if not materias:
        messages.error(request, 'Elige al menos una materia.')
        return _volver_al_perfil(request, profesor)

    nuevas = habilitar(profesor, materias)
    if nuevas:
        nombres = ', '.join(materia.nombre for materia in nuevas)
        registrar(request.user, profesor, ACCION_CAMBIO, f'Habilitado para impartir: {nombres}.')
        messages.success(request, f'{profesor} puede impartir ahora {nombres}.')
    else:
        messages.info(request, 'Esas materias ya estaban en su lista.')
    return _volver_al_perfil(request, profesor)


@require_POST
@requiere_permisos('Alumnos.change_profesor')
def profesor_deshabilitar(request, pk):
    """Quita materias de las que el profesor puede impartir. No toca lo que ya imparte: eso se quita en las asignaciones."""
    profesor = get_object_or_404(Profesor, pk=pk)
    materias = deshabilitar(profesor, solo_numeros(request.POST.getlist('materia')))
    if not materias:
        messages.error(request, 'Elige al menos una materia.')
        return _volver_al_perfil(request, profesor)

    nombres = ', '.join(materia.nombre for materia in materias)
    registrar(request.user, profesor, ACCION_CAMBIO, f'Ya no está habilitado para impartir: {nombres}.')
    messages.success(request, f'{profesor} ya no tiene {nombres} en su lista de materias que puede impartir.')

    sigue = MateriaGrado.objects.filter(profesor=profesor, materia__in=materias, ciclo__activo=True, activa=True).count()
    if sigue:
        messages.info(
            request,
            f'Sigue impartiendo {sigue} grupo{"s" if sigue != 1 else ""} de esas materias en el ciclo actual: '
            'quítalo de ahí desde «Materias» si ya no las dará.',
        )
    return _volver_al_perfil(request, profesor)


# ---------------------------------------------------------------------------
# Asignar (o quitar) al profesor de una o varias materias de un grado
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.change_materiagrado')
def asignar(request):
    """Fija quién imparte cada materia (de un grado, en un ciclo). Sin `profesor` se quita al que estaba.

    Lo usan el perfil del profesor (varias materias), el del grado y el de la materia (una). Se revisa que el
    ciclo no esté cerrado y que el profesor no quede en dos grupos a la vez; lo que no se puede se omite y se avisa.
    """
    destino = destino_seguro(request, reverse('profesores:lista'))
    asignaciones = list(
        MateriaGrado.objects.filter(pk__in=solo_numeros(request.POST.getlist('asignacion')))
        .select_related('materia', 'grado', 'ciclo', 'profesor').prefetch_related('horarios')
    )
    if not asignaciones:
        messages.error(request, 'Elige al menos una materia.')
        return redirect(destino)

    profesor = None
    valor = request.POST.get('profesor', '')
    if valor:
        profesor = Profesor.objects.filter(pk=valor, estatus='ACTIVO').first() if valor.isdigit() else None
        if profesor is None:
            messages.error(request, 'Elige un profesor activo.')
            return redirect(destino)

    cambios, omitidas = asignar_profesor(asignaciones, profesor)
    for asignacion, anterior in cambios:
        registrar(request.user, asignacion, ACCION_CAMBIO, descripcion_del_cambio(asignacion, anterior))
    hechas = len(cambios)

    if hechas:
        if profesor:
            messages.success(request, f'{profesor} imparte ahora {hechas} materia{"s" if hechas != 1 else ""} más.' if len(asignaciones) > 1
                             else f'{profesor} imparte ahora {asignaciones[0].materia} en {asignaciones[0].grado}.')
        else:
            messages.success(request, f'Se quitó al profesor de {hechas} materia{"s" if hechas != 1 else ""}.')
    elif not omitidas:
        messages.info(request, 'No hubo cambios: esas materias ya tenían ese profesor.')
    for motivo in omitidas[:5]:
        messages.error(request, f'No se pudo asignar. {motivo}')
    if len(omitidas) > 5:
        messages.error(request, f'Y {len(omitidas) - 5} más con el mismo problema.')
    return redirect(destino)


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@require_GET
@requiere_permisos('Alumnos.view_profesor')
def profesor_exportar(request):
    filtro = FiltroProfesoresForm(request.GET)
    ciclo = ciclo_actual()
    profesores = list(filtro.filtrar(Profesor.objects.all(), ciclo).prefetch_related('niveles'))

    materias = defaultdict(list)
    if ciclo:
        asignaciones = (
            MateriaGrado.objects.filter(ciclo=ciclo, activa=True, profesor__in=[p.pk for p in profesores])
            .select_related('materia', 'grado').order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'materia__nombre')
        )
        for asignacion in asignaciones:
            materias[asignacion.profesor_id].append(f'{asignacion.materia} ({asignacion.grado})')

    habilitadas = defaultdict(list)
    for profesor_id, nombre in (
        ProfesorMateria.objects.filter(profesor__in=[p.pk for p in profesores]).order_by('materia__nombre')
        .values_list('profesor_id', 'materia__nombre')
    ):
        habilitadas[profesor_id].append(nombre)

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="profesores-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta.write('﻿')  # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    escritor.writerow([
        'Nombre', 'Apellido paterno', 'Apellido materno', 'CURP', 'Teléfono', 'Teléfono alternativo', 'Correo electrónico',
        'Niveles', 'Profesión', 'Cédula profesional', 'Especialidad', 'Fecha de ingreso', 'Estatus',
        f'Materias en el ciclo actual{f" ({ciclo})" if ciclo else ""}', 'Materias que puede impartir', 'Horas máximas por semana',
    ])
    for profesor in profesores:
        escritor.writerow([proteger_celda_csv(valor) for valor in [
            profesor.nombre, profesor.apellido_paterno, profesor.apellido_materno, profesor.curp or '', profesor.telefono,
            profesor.telefono_alternativo, profesor.correo_electronico or '', profesor.niveles_texto, profesor.profesion,
            profesor.cedula_profesional,
            profesor.especialidad, f'{profesor.fecha_ingreso:%d/%m/%Y}' if profesor.fecha_ingreso else '',
            profesor.get_estatus_display(), '; '.join(materias.get(profesor.pk, [])),
            '; '.join(habilitadas.get(profesor.pk, [])), profesor.horas_maximas or '',
        ]])
    return respuesta
