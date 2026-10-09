from django.contrib import messages
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_editable, elegir_ciclo
from Alumnos.models import ORDEN_NIVELES, CicloEscolar, Periodo
from Alumnos.periodos import describir, periodos_por_nivel
from CISAHUAYO.permisos import requiere_permisos
from Usuarios.seguridad import ACCION_ALTA, ACCION_BAJA, ACCION_CAMBIO, registrar

from .forms import PeriodoForm


def _ciclo_de(request):
    """Ciclo que se consulta: ?ciclo=, si no el actual y, si no hay, el más reciente."""
    ciclos = list(CicloEscolar.objects.all())
    return ciclos, elegir_ciclo(request.GET.get('ciclo', ''), ciclos)


def _lista(ciclo_id):
    return f"{reverse('periodos:lista')}?ciclo={ciclo_id}"


def _fechas(periodo):
    """«del 19 de octubre al 18 de diciembre de 2026» (en español los meses van en minúscula)."""
    inicio = date_format(periodo.fecha_inicio, 'j \\d\\e F').lower()
    fin = date_format(periodo.fecha_fin, 'j \\d\\e F \\d\\e Y').lower()
    return f'del {inicio} al {fin}'


def _ciclo_cerrado(request, ciclo):
    messages.error(request, f'El ciclo {ciclo} está cerrado: sus periodos se conservan tal como quedaron y ya no se modifican.')
    return redirect(_lista(ciclo.pk))


# ---------------------------------------------------------------------------
# Los periodos de cada nivel, en tarjetas
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_periodo')
def periodo_lista(request):
    ciclos, ciclo = _ciclo_de(request)
    niveles = periodos_por_nivel(ciclo)
    return render(request, 'periodos/lista.html', {
        'ciclos': ciclos,
        'ciclo': ciclo,
        'niveles': niveles,
        'total': sum(len(nivel['periodos']) for nivel in niveles),
        'abiertos': [periodo for nivel in niveles for periodo in nivel['abiertos']],
        'editable': ciclo_editable(ciclo),
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, periodo=None):
    return render(request, 'periodos/form.html', {
        'form': form, 'periodo': periodo, 'ciclo': form.ciclo, 'es_edicion': periodo is not None,
    })


@requiere_permisos('Alumnos.add_periodo')
def periodo_crear(request):
    _, ciclo = _ciclo_de(request)
    if ciclo is None:
        messages.error(request, 'Crea un ciclo escolar para poder agregar sus periodos.')
        return redirect('periodos:lista')
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, ciclo)

    if request.method == 'POST':
        form = PeriodoForm(request.POST, ciclo=ciclo)
        if form.is_valid():
            periodo = form.save()
            registrar(request.user, periodo, ACCION_ALTA, f'Periodo de {periodo.get_nivel_display()} {_fechas(periodo)}.')
            messages.success(request, f'Se agregó «{periodo.nombre}» a {periodo.get_nivel_display()}: {_fechas(periodo)}. {describir(periodo)}')
            return redirect(_lista(ciclo.pk))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        nivel = request.GET.get('nivel', '')
        form = PeriodoForm(ciclo=ciclo, initial={'nivel': nivel} if nivel in ORDEN_NIVELES else {})
    return _formulario(request, form)


@requiere_permisos('Alumnos.change_periodo')
def periodo_editar(request, pk):
    periodo = get_object_or_404(Periodo.objects.select_related('ciclo'), pk=pk)
    if not ciclo_editable(periodo.ciclo):
        return _ciclo_cerrado(request, periodo.ciclo)

    form = PeriodoForm(request.POST if request.method == 'POST' else None, instance=periodo)
    if request.method == 'POST':
        if form.is_valid():
            periodo = form.save()
            registrar(request.user, periodo, ACCION_CAMBIO, f'Datos: {periodo.get_nivel_display()} {_fechas(periodo)}.')
            messages.success(request, f'Se actualizó «{periodo.nombre}» de {periodo.get_nivel_display()}. {describir(periodo)}')
            return redirect(_lista(periodo.ciclo_id))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, periodo)


# ---------------------------------------------------------------------------
# Abrir o cerrar a mano, volver a sus fechas y eliminar
# ---------------------------------------------------------------------------
def _cambiar_apertura(request, pk, apertura, aviso):
    periodo = get_object_or_404(Periodo.objects.select_related('ciclo'), pk=pk)
    if not ciclo_editable(periodo.ciclo):
        return _ciclo_cerrado(request, periodo.ciclo)
    if periodo.apertura != apertura:
        periodo.apertura = apertura
        periodo.save(update_fields=['apertura', 'modificado'])
        registrar(request.user, periodo, ACCION_CAMBIO, f'Apertura: {periodo.get_apertura_display().lower()}.')
    messages.success(request, aviso(periodo))
    return redirect(_lista(periodo.ciclo_id))


@require_POST
@requiere_permisos('Alumnos.change_periodo')
def periodo_abrir(request, pk):
    return _cambiar_apertura(request, pk, Periodo.ABIERTO, lambda p: (
        f'«{p.nombre}» de {p.get_nivel_display()} quedó abierto: los profesores de {p.get_nivel_display()} pueden '
        f'capturar hasta que lo cierres.'
    ))


@require_POST
@requiere_permisos('Alumnos.change_periodo')
def periodo_cerrar(request, pk):
    return _cambiar_apertura(request, pk, Periodo.CERRADO, lambda p: (
        f'«{p.nombre}» de {p.get_nivel_display()} quedó cerrado: ya no se puede capturar en él hasta que lo abras.'
    ))


@require_POST
@requiere_permisos('Alumnos.change_periodo')
def periodo_por_fechas(request, pk):
    return _cambiar_apertura(request, pk, Periodo.POR_FECHAS, lambda p: (
        f'«{p.nombre}» de {p.get_nivel_display()} vuelve a seguir sus fechas ({_fechas(p)}): '
        f'hoy está {p.estado_display.lower()}.'
    ))


@require_POST
@requiere_permisos('Alumnos.delete_periodo')
def periodo_eliminar(request, pk):
    periodo = get_object_or_404(Periodo.objects.select_related('ciclo'), pk=pk)
    if not ciclo_editable(periodo.ciclo):
        return _ciclo_cerrado(request, periodo.ciclo)
    ciclo_id, descripcion = periodo.ciclo_id, f'«{periodo.nombre}» de {periodo.get_nivel_display()}'
    try:
        registrar(request.user, periodo, ACCION_BAJA, f'Eliminado: {periodo.get_nivel_display()} {_fechas(periodo)}.')
        periodo.delete()
    except ProtectedError:   # cuando haya calificaciones capturadas en él
        messages.error(request, f'{descripcion} ya tiene información capturada y no se puede eliminar. Puedes cerrarlo.')
        return redirect(_lista(ciclo_id))
    messages.success(request, f'Se eliminó {descripcion}.')
    return redirect(_lista(ciclo_id))
