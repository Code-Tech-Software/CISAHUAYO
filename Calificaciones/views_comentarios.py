"""Comentarios por periodo (pedido del 2026-11-09): la captura del docente (Gestión académica › Comentarios por periodo),
las boletas de comentarios de un estudiante y de un grupo, su publicación y su reapertura.

Las reglas están en Calificaciones/comentarios.py. La captura sigue los permisos de Calificaciones: un docente, sus
materias; con «ver o gestionar todas», las de todo el colegio (solo «gestionar» escribe). Las boletas las abren
quienes ven todas las calificaciones, como la de calificaciones; publicar pide su propio permiso y reabrir, el de
reabrir calificaciones. La hoja para imprimir o guardar en PDF es como la de la boleta de calificaciones; el
estudiante y sus tutores la abren desde su portal cuando está publicada (PortalEstudiantes y PortalTutores).
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_actual
from Alumnos.models import Alumno, Grupo, Periodo
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from Usuarios.docentes import profesor_de

from . import comentarios, reglas
from .forms import MotivoForm

VER = (reglas.VER_TODAS, reglas.GESTIONAR_TODAS)


def _elegir(lista, pedido):
    return next((x for x in lista if str(x.pk) == str(pedido)), None) if pedido else None


def _quien(usuario):
    return usuario.get_full_name() or usuario.get_username()


def url_de_captura(asignacion, periodo):
    return f"{reverse('calificaciones:comentarios')}?{urlencode({'ciclo': asignacion.ciclo_id, 'materia': asignacion.pk, 'periodo': periodo.pk})}"


def url_del_estudiante(alumno, periodo):
    return f"{reverse('calificaciones:boletas_periodo', args=[alumno.pk])}?{urlencode({'periodo': periodo.pk})}"


def url_del_grupo(grupo, periodo):
    return f"{reverse('calificaciones:comentarios_grupo', args=[grupo.pk])}?{urlencode({'periodo': periodo.pk})}"


# ---------------------------------------------------------------------------
# La captura del docente
# ---------------------------------------------------------------------------
@requiere_alguno(*reglas.ENTRAR)
def captura(request):
    usuario = request.user
    ciclos = reglas.ciclos_con_materias(usuario)
    actual = ciclo_actual()
    ciclo = _elegir(ciclos, request.GET.get('ciclo')) or (actual if actual in ciclos else (ciclos[0] if ciclos else None))
    asignaciones = list(reglas.asignaciones_para(usuario, ciclo)) if ciclo else []
    contexto = {'ciclos': ciclos, 'ciclo': ciclo, 'asignaciones': asignaciones, 've_todas': reglas.ve_todas(usuario), 'profesor': profesor_de(usuario)}
    elegida = request.GET.get('materia', '')
    if not asignaciones:
        if elegida:
            raise PermissionDenied   # una materia pedida que no puede abrir (aunque no tenga ninguna)
        return render(request, 'calificaciones/comentarios.html', contexto)
    if elegida:
        asignacion = _elegir(asignaciones, elegida)
        if asignacion is None:
            raise PermissionDenied
    else:
        grupo = request.GET.get('grupo', '')
        asignacion = next((a for a in asignaciones if str(a.grupo_id) == grupo), asignaciones[0])
    periodos = reglas.periodos_de(asignacion)
    periodo = _elegir(periodos, request.GET.get('periodo')) or reglas.periodo_sugerido(periodos)
    contexto.update({
        'asignacion': asignacion, 'grupos': list({a.grupo_id: a.grupo for a in asignaciones}.values()),
        'materias_del_grupo': [a for a in asignaciones if a.grupo_id == asignacion.grupo_id], 'periodos': periodos, 'periodo': periodo,
    })
    if periodo is None:
        return render(request, 'calificaciones/comentarios.html', contexto)

    motivo = comentarios.motivo_de_solo_lectura(asignacion, periodo, usuario)
    url = url_de_captura(asignacion, periodo)
    enviados, errores = {}, {}
    if request.method == 'POST':
        if not reglas.puede_capturar(usuario, asignacion):
            raise PermissionDenied
        filas = comentarios.captura(asignacion, periodo).filas
        enviados = {f.inscripcion.pk: (request.POST[f'comentario-{f.inscripcion.pk}'], request.POST.get(f'version-{f.inscripcion.pk}', ''))
                    for f in filas if f'comentario-{f.inscripcion.pk}' in request.POST}
        try:
            guardados, errores = comentarios.guardar(asignacion, periodo, usuario, enviados)
        except comentarios.ComentarioRechazado as error:
            messages.error(request, error.mensaje)
            return redirect(url)
        texto = (f'Se guardaron {guardados} comentarios.' if guardados != 1 else 'Se guardó 1 comentario.') if guardados else 'No había cambios por guardar.'
        if not errores:
            messages.success(request, texto)
            return redirect(url)
        aviso = 'Uno no se guardó: revisa el marcado.' if len(errores) == 1 else f'{len(errores)} no se guardaron: revisa los marcados.'
        messages.warning(request, f'{texto} {aviso}')

    datos = comentarios.captura(asignacion, periodo)
    for fila in datos.filas:
        pk = fila.inscripcion.pk
        fila.error = errores.get(pk, '')
        # Si no se guardó, se le devuelve lo que escribió (no se pierde)
        fila.escrito = comentarios.limpiar(enviados[pk][0]) if fila.error and pk in enviados else fila.texto
    contexto.update({
        'captura': datos, 'editable': not motivo, 'solo_lectura': motivo, 'url': url, 'limite': comentarios.LIMITE,
        'boletas_del_grupo': url_del_grupo(asignacion.grupo, periodo) if reglas.ve_todas(usuario) and not asignacion.es_de_clase else '',
        'url_calificaciones': f"{reverse('calificaciones:inicio')}?{urlencode({'ciclo': asignacion.ciclo_id, 'materia': asignacion.pk, 'periodo': periodo.pk})}",
    })
    return render(request, 'calificaciones/comentarios.html', contexto)


# ---------------------------------------------------------------------------
# Las boletas de un estudiante en un periodo: la de calificaciones y la de comentarios
# ---------------------------------------------------------------------------
def _periodo_pedido(pares, pedido):
    """(periodo, inscripción) pedido; si no, el abierto hoy o el último que empezó del ciclo actual; si no, el más reciente."""
    elegido = next(((p, i) for p, i in pares if str(p.pk) == str(pedido)), None) if pedido else None
    if elegido:
        return elegido
    actual = ciclo_actual()
    del_actual = sorted((p for p, i in pares if actual and p.ciclo_id == actual.pk), key=lambda p: (p.fecha_inicio, p.pk))
    sugerido = reglas.periodo_sugerido(del_actual) if del_actual else None
    return next(((p, i) for p, i in pares if sugerido and p.pk == sugerido.pk), pares[0])


@requiere_alguno(*VER)
def boletas_periodo(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    pares = comentarios.periodos_del_alumno(alumno)
    if not pares:
        messages.info(request, f'{alumno} no tiene periodos de evaluación en sus inscripciones: todavía no hay boletas.')
        return redirect(f'{alumno.get_absolute_url()}#academico')
    periodo, inscripcion = _periodo_pedido(pares, request.GET.get('periodo'))
    boleta = comentarios.boleta_de(inscripcion, periodo)
    bloqueo = comentarios.bloqueo_de_reapertura(periodo) if boleta.publicada else ''
    return render(request, 'calificaciones/boletas_periodo.html', {
        'alumno': alumno, 'pares': pares, 'periodo': periodo, 'inscripcion': inscripcion, 'boleta': boleta,
        'puede_publicar': request.user.has_perm(comentarios.PUBLICAR) and not boleta.publicada,
        'problemas': comentarios.problemas_para_publicar(boleta),
        'puede_reabrir': boleta.publicada and not bloqueo and request.user.has_perm(reglas.REABRIR),
        'bloqueo_reapertura': bloqueo if request.user.has_perm(reglas.REABRIR) else '',
        'motivo_form': MotivoForm(), 'historial': comentarios.historial(inscripcion, periodo),
    })


def _alumno_y_periodo(pk, pedido):
    alumno = get_object_or_404(Alumno, pk=pk)
    if not str(pedido or '').isdigit():
        raise Http404
    periodo = get_object_or_404(Periodo.objects.select_related('ciclo', 'semestre'), pk=pedido)
    inscripcion = comentarios.inscripcion_del_periodo(alumno, periodo)
    if inscripcion is None:
        raise Http404
    return alumno, periodo, inscripcion


@require_POST
@requiere_permisos(comentarios.PUBLICAR)
def publicar(request, pk):
    alumno, periodo, inscripcion = _alumno_y_periodo(pk, request.POST.get('periodo'))
    try:
        comentarios.publicar(inscripcion, periodo, request.user)
        messages.success(request, f'Se publicó la boleta de comentarios de {alumno} ({periodo.nombre}): ya la ven el estudiante y sus tutores en su portal.')
    except comentarios.ComentarioRechazado as error:
        messages.error(request, f'No se publicó: {error.mensaje}')
    return redirect(url_del_estudiante(alumno, periodo))


@require_POST
@requiere_permisos(reglas.REABRIR)
def reabrir(request, pk):
    alumno, periodo, inscripcion = _alumno_y_periodo(pk, request.POST.get('periodo'))
    if not reglas.ve_todas(request.user):
        raise PermissionDenied
    form = MotivoForm(request.POST)
    if not form.is_valid():
        messages.error(request, ' '.join(form.errors.get('motivo', ['Escribe el motivo.'])))
        return redirect(url_del_estudiante(alumno, periodo))
    try:
        comentarios.reabrir(inscripcion, periodo, form.cleaned_data['motivo'], request.user)
        messages.success(request, f'Se reabrió la boleta de comentarios de {alumno} ({periodo.nombre}): sus docentes ya pueden corregir los comentarios '
                                  'mientras el periodo esté abierto. El portal ya no la muestra hasta que se vuelva a publicar.')
    except comentarios.ComentarioRechazado as error:
        messages.error(request, error.mensaje)
    return redirect(url_del_estudiante(alumno, periodo))


# ---------------------------------------------------------------------------
# La hoja para imprimir o guardar en PDF
# ---------------------------------------------------------------------------
def hoja(request, boletas, titulo, volver, usuario=''):
    """Las boletas de comentarios en una sola hoja (cada una en su página al imprimir). `boletas` son
    comentarios.BoletaDeComentarios (lo publicado o, si no se ha publicado, el borrador)."""
    return render(request, 'calificaciones/boleta_comentarios_hoja.html', {
        'hojas': [{'c': b.contenido, 'publicada': b.publicada, 'registro': b.registro, 'pendientes': len(b.pendientes) if not b.publicada else 0}
                  for b in boletas],
        'titulo': titulo, 'volver': volver, 'imprimir_al_abrir': request.GET.get('pdf') == '1', 'generado': timezone.localtime(), 'usuario': usuario,
    })


@requiere_alguno(*VER)
def boleta_comentarios(request, pk):
    alumno, periodo, inscripcion = _alumno_y_periodo(pk, request.GET.get('periodo'))
    boleta = comentarios.boleta_de(inscripcion, periodo)
    return hoja(request, [boleta], f'Boleta de comentarios · {alumno} · {periodo.nombre}', url_del_estudiante(alumno, periodo), _quien(request.user))


# ---------------------------------------------------------------------------
# Las boletas de comentarios de un grupo
# ---------------------------------------------------------------------------
def _grupo_y_periodo(request, pk, pedido):
    grupo = get_object_or_404(Grupo.objects.select_related('grado', 'nombre'), pk=pk)
    ciclo = ciclo_actual()
    periodo = None
    if str(pedido or '').isdigit():
        periodo = Periodo.objects.select_related('ciclo', 'semestre').filter(pk=pedido, nivel=grupo.grado.nivel).first()
        if periodo is None:
            raise Http404
        ciclo = periodo.ciclo
    periodos = comentarios.periodos_del_grado(grupo.grado, ciclo) if ciclo else []
    if periodo is None:
        periodo = reglas.periodo_sugerido(periodos) if periodos else None
    return grupo, periodo, periodos


@requiere_alguno(*VER)
def comentarios_grupo(request, pk):
    grupo, periodo, periodos = _grupo_y_periodo(request, pk, request.GET.get('periodo') or request.POST.get('periodo'))
    if periodo is None:
        messages.info(request, f'El nivel de {grupo} no tiene periodos de evaluación en el ciclo actual.')
        return redirect('calificaciones:comentarios')
    if request.method == 'POST':
        if not request.user.has_perm(comentarios.PUBLICAR):
            raise PermissionDenied
        publicadas, fallidas = 0, 0
        for boleta in comentarios.boletas_del_grupo(grupo, periodo):
            if boleta.completa and not boleta.publicada:
                try:
                    comentarios.publicar(boleta.inscripcion, periodo, request.user)
                    publicadas += 1
                except comentarios.ComentarioRechazado:
                    fallidas += 1
        if publicadas:
            messages.success(request, f'Se publicaron {publicadas} boleta{"s" if publicadas != 1 else ""} de comentarios de {grupo} ({periodo.nombre}).')
        else:
            messages.info(request, 'No había boletas completas sin publicar.')
        if fallidas:
            messages.warning(request, f'{fallidas} no se publicaron porque cambiaron mientras tanto: revísalas.')
        return redirect(url_del_grupo(grupo, periodo))
    boletas = comentarios.boletas_del_grupo(grupo, periodo)
    return render(request, 'calificaciones/comentarios_grupo.html', {
        'grupo': grupo, 'periodo': periodo, 'periodos': periodos, 'boletas': boletas,
        'listas': sum(1 for b in boletas if b.estado == 'lista'), 'publicadas': sum(1 for b in boletas if b.publicada),
        'puede_publicar': request.user.has_perm(comentarios.PUBLICAR),
    })


@requiere_alguno(*VER)
def comentarios_grupo_hoja(request, pk):
    grupo, periodo, _ = _grupo_y_periodo(request, pk, request.GET.get('periodo'))
    if periodo is None:
        raise Http404
    boletas = [b for b in comentarios.boletas_del_grupo(grupo, periodo) if b.materias]
    if not boletas:
        messages.info(request, f'{grupo} no tiene estudiantes con materias en {periodo.nombre}.')
        return redirect(url_del_grupo(grupo, periodo))
    return hoja(request, boletas, f'Boletas de comentarios · {grupo} · {periodo.nombre}', url_del_grupo(grupo, periodo), _quien(request.user))
