"""Gestión de los retiros anticipados (personal del colegio) y su configuración en Ajustes › Retiros.

- Lista: los de hoy (vista principal, por hora, con lo que falta por confirmar) y todos, con búsqueda por estudiante,
  tutor o folio y filtros de fechas, nivel, grado, grupo, motivo y estado. Una fila por estudiante: cada uno sale por
  separado.
- Detalle: el aviso (lo que ve el tutor), quién recoge y si sigue autorizado, cada estudiante con sus acciones, las
  observaciones internas (el tutor no las ve) y la bitácora.
- Confirmar la salida, cancelar y corregir abren su formulario en una ventana (data-modal-form) o como página.
Todo dentro del alcance de la cuenta (Retiros/alcance.py): lo de fuera responde 404.
"""
from django.contrib import messages
from django.db.models import Count, ProtectedError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos

from . import notificaciones, reglas
from .alcance import CONFIGURAR, CONFIRMAR, CORREGIR, DEL_PERSONAL, SIN_NIVELES, alcance_de, condicion, permite
from .context_processors import datos_de_avisos
from .forms import CancelarForm, ConfirmarSalidaForm, CorregirSalidaForm, FiltroRetirosForm, MotivoForm, NotaForm
from .models import AvisoRetiro, MotivoRetiro, RetiroEstudiante


def puede(usuario):
    return {'confirmar': usuario.has_perm(CONFIRMAR), 'corregir': usuario.has_perm(CORREGIR)}


def _retiros_del_alcance(usuario):
    return RetiroEstudiante.objects.filter(condicion(alcance_de(usuario)))


def _con_relaciones(consulta):
    return consulta.select_related(
        'alumno', 'inscripcion__grado', 'inscripcion__grupo__grado', 'inscripcion__grupo__nombre',
        'aviso__tutor', 'aviso__recoge', 'aviso__motivo', 'recogio', 'confirmado_por',
    )


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------
@requiere_alguno(*DEL_PERSONAL)
def lista(request):
    alcance = alcance_de(request.user)
    vista = 'todos' if request.GET.get('vista') == 'todos' else 'hoy'
    hoy = timezone.localdate()
    filtro = FiltroRetirosForm(request.GET or None, alcance=alcance)
    consulta = _retiros_del_alcance(request.user)
    if vista == 'hoy':
        del_dia = consulta.filter(fecha=hoy)
        totales = dict(del_dia.order_by().values_list('estado').annotate(total=Count('pk')))
        filas = _con_relaciones(filtro.filtrar(del_dia, con_fechas=False)).order_by('aviso__hora', 'alumno__nombre')
        pendientes = [r for r in filas if r.estado == RetiroEstudiante.AVISADO]
        atendidos = [r for r in filas if r.estado != RetiroEstudiante.AVISADO]
        contexto = {'pendientes': pendientes, 'atendidos': atendidos,
                    'totales': [(clave, nombre, totales.get(clave, 0)) for clave, nombre in RetiroEstudiante.ESTADOS]}
    else:
        filas = _con_relaciones(filtro.filtrar(consulta)).order_by('-fecha', '-aviso__hora', 'alumno__nombre')
        pagina, rango_paginas, por_pagina = paginar(request, filas)
        contexto = {'pagina': pagina, 'rango_paginas': rango_paginas, 'por_pagina': por_pagina,
                    'por_pagina_defecto': POR_PAGINA_DEFECTO, 'opciones_por_pagina': OPCIONES_POR_PAGINA}
    return render(request, 'retiros/lista.html', {
        **contexto, 'vista': vista, 'hoy': hoy, 'filtro': filtro, 'mas_filtros': filtro.activos, 'alcance': alcance,
        'sin_niveles': SIN_NIVELES if alcance.vacio else '', 'puede': puede(request.user),
        'clases': reglas.TONO_DE_ESTADO,
    })


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
def _aviso(request, pk):
    """El aviso (404 si ninguno de sus estudiantes es del alcance) y sus estudiantes del alcance."""
    aviso = get_object_or_404(AvisoRetiro.objects.select_related('tutor', 'recoge', 'motivo'), pk=pk)
    retiros = list(_con_relaciones(_retiros_del_alcance(request.user).filter(aviso=aviso)))
    if not retiros:
        raise Http404('Ese aviso no existe o no es de tus niveles.')
    return aviso, retiros


def _retiro(request, pk):
    retiro = get_object_or_404(_con_relaciones(RetiroEstudiante.objects.all()), pk=pk)
    if not permite(alcance_de(request.user), retiro):
        raise Http404('Ese retiro no existe o no es de tus niveles.')
    return retiro


@requiere_alguno(*DEL_PERSONAL)
def detalle(request, pk):
    aviso, retiros = _aviso(request, pk)
    notificaciones.marcar_leidas(aviso, usuario=request.user)
    autorizados = reglas.autorizados_para([r.alumno_id for r in retiros])
    for retiro in retiros:
        retiro.recoge_autorizado = aviso.recoge_id in autorizados.get(retiro.alumno_id, {})
        retiro.vinculo_recoge = autorizados.get(retiro.alumno_id, {}).get(aviso.recoge_id)
    total = aviso.estudiantes.count()
    return render(request, 'retiros/detalle.html', {
        'aviso': aviso, 'retiros': retiros, 'ocultos': total - len(retiros),
        'estado': reglas.estado_general(retiros), 'clases': reglas.TONO_DE_ESTADO,
        'notas': aviso.notas.select_related('autor'), 'eventos': aviso.eventos.select_related('usuario', 'tutor', 'estudiante__alumno'),
        'nota_form': NotaForm(), 'puede': puede(request.user), 'es_hoy': aviso.fecha == timezone.localdate(),
        'cancelables': [r for r in retiros if r.estado == RetiroEstudiante.AVISADO],
    })


@require_POST
@requiere_alguno(*DEL_PERSONAL)
def nota(request, pk):
    aviso, _ = _aviso(request, pk)
    form = NotaForm(request.POST)
    if form.is_valid():
        reglas.agregar_nota(aviso, request.user, form.cleaned_data['texto'])
        messages.success(request, 'Se guardó la observación interna (el tutor no la ve).')
    else:
        messages.error(request, 'Escribe la observación.')
    return redirect(f"{reverse('retiros:detalle', args=[aviso.pk])}#notas")


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------
@requiere_permisos(CONFIRMAR)
def confirmar(request, pk):
    retiro = _retiro(request, pk)
    volver = reverse('retiros:detalle', args=[retiro.aviso_id])
    if retiro.estado != RetiroEstudiante.AVISADO:
        messages.info(request, f'El retiro de {retiro.alumno.nombre} ya no está pendiente ({retiro.get_estado_display().lower()}).')
        return redirect(volver)
    form = ConfirmarSalidaForm(request.POST or None, retiro=retiro)
    if request.method == 'POST' and form.is_valid():
        try:
            reglas.confirmar_salida(retiro, request.user, form.persona(), form.momento(), form.cleaned_data['observaciones'])
        except reglas.RetiroRechazado as rechazo:
            for mensaje in rechazo.mensajes:
                form.add_error(None, mensaje)
        else:
            messages.success(request, f'Se confirmó la salida de {retiro.alumno.nombre}. Se avisó al tutor.')
            return redirect(volver)
    return render(request, 'retiros/confirmar.html', {
        'retiro': retiro, 'form': form, 'volver': volver, 'sin_autorizados': not form.fields['recogio'].choices,
        'recoge_autorizado': retiro.aviso.recoge_id in form.vinculos,
    })


@requiere_permisos(CORREGIR)
def cancelar(request, pk):
    aviso, retiros = _aviso(request, pk)
    volver = reverse('retiros:detalle', args=[aviso.pk])
    cancelables = [r for r in retiros if r.estado == RetiroEstudiante.AVISADO]
    if not cancelables:
        messages.info(request, 'Este aviso ya no tiene estudiantes por cancelar.')
        return redirect(volver)
    form = CancelarForm(request.POST or None, retiros=cancelables, motivo_obligatorio=True)
    if request.method == 'POST' and form.is_valid():
        try:
            cancelados = reglas.cancelar_por_personal(aviso, request.user, form.cleaned_data['retiros'], form.cleaned_data['motivo'])
        except reglas.RetiroRechazado as rechazo:
            for mensaje in rechazo.mensajes:
                form.add_error(None, mensaje)
        else:
            messages.success(request, f'Se canceló el retiro de {", ".join(r.alumno.nombre for r in cancelados)}. Se avisó al tutor.')
            return redirect(volver)
    return render(request, 'retiros/cancelar.html', {'aviso': aviso, 'form': form, 'volver': volver})


@requiere_permisos(CORREGIR)
def corregir(request, pk):
    retiro = _retiro(request, pk)
    volver = reverse('retiros:detalle', args=[retiro.aviso_id])
    if retiro.estado != RetiroEstudiante.RETIRADO:
        messages.info(request, 'Solo se corrigen salidas ya confirmadas.')
        return redirect(volver)
    form = CorregirSalidaForm(request.POST or None, retiro=retiro)
    if request.method == 'POST' and form.is_valid():
        try:
            if form.deshacer:
                reglas.corregir_salida(retiro, request.user, form.cleaned_data['motivo'], deshacer=True)
            else:
                reglas.corregir_salida(retiro, request.user, form.cleaned_data['motivo'], recogio=form.persona(),
                                       momento=form.momento(), observaciones=form.cleaned_data['observaciones'])
        except reglas.RetiroRechazado as rechazo:
            for mensaje in rechazo.mensajes:
                form.add_error(None, mensaje)
        else:
            messages.success(request, f'Se corrigió la salida de {retiro.alumno.nombre}. Queda en la bitácora y se avisó al tutor.')
            return redirect(volver)
    return render(request, 'retiros/corregir.html', {'retiro': retiro, 'form': form, 'volver': volver})


@require_GET
@requiere_alguno(*DEL_PERSONAL)
def resumen(request):
    """Las notificaciones sin leer (la campana, al reconectarse o al volver a la pestaña)."""
    return JsonResponse(datos_de_avisos(usuario=request.user))


# ---------------------------------------------------------------------------
# Ajustes › Retiros: motivos
# ---------------------------------------------------------------------------
def _ajustes(request):
    """Lo que necesitan las pestañas de Ajustes (templates/ajustes/_pestanas.html)."""
    from Conducta.permisos import puede_configurar
    return {'ajustes_seccion': 'retiros', 'puede_configurar_conducta': puede_configurar(request.user)}


@requiere_permisos(CONFIGURAR)
def motivos(request):
    lista_de_motivos = MotivoRetiro.objects.annotate(usos=Count('avisos'))
    return render(request, 'retiros/motivos.html', {'motivos': lista_de_motivos, **_ajustes(request)})


@requiere_permisos(CONFIGURAR)
def motivo_crear(request):
    siguiente = (MotivoRetiro.objects.order_by('-orden').values_list('orden', flat=True).first() or 0) + 10
    form = MotivoForm(request.POST or None, initial={'orden': siguiente, 'activo': True})
    if request.method == 'POST' and form.is_valid():
        motivo = form.save()
        messages.success(request, f'Se agregó el motivo «{motivo}».')
        return redirect('retiros:motivos')
    return render(request, 'retiros/motivo_form.html', {'form': form, **_ajustes(request)})


@requiere_permisos(CONFIGURAR)
def motivo_editar(request, pk):
    motivo = get_object_or_404(MotivoRetiro, pk=pk)
    form = MotivoForm(request.POST or None, instance=motivo)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Se guardó el motivo «{motivo}».')
        return redirect('retiros:motivos')
    return render(request, 'retiros/motivo_form.html', {'form': form, 'motivo': motivo, 'usado': motivo.avisos.exists(),
                                                        **_ajustes(request)})


@require_POST
@requiere_permisos(CONFIGURAR)
def motivo_activo(request, pk):
    motivo = get_object_or_404(MotivoRetiro, pk=pk)
    motivo.activo = not motivo.activo
    motivo.save(update_fields=['activo', 'modificado'])
    if motivo.activo:
        messages.success(request, f'«{motivo}» se vuelve a ofrecer en los avisos nuevos.')
    else:
        messages.success(request, f'«{motivo}» ya no se ofrece en los avisos nuevos (los registrados lo conservan).')
    return redirect('retiros:motivos')


@require_POST
@requiere_permisos(CONFIGURAR)
def motivo_eliminar(request, pk):
    motivo = get_object_or_404(MotivoRetiro, pk=pk)
    try:
        motivo.delete()
    except ProtectedError:
        messages.error(request, f'«{motivo}» ya se usó en avisos: no se elimina para no perder el historial. Desactívalo para dejar de ofrecerlo.')
    else:
        messages.success(request, f'Se eliminó el motivo «{motivo}».')
    return redirect('retiros:motivos')
