from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from Alumnos.academico import activar_ciclo, alumnos_sin_inscribir, ciclo_actual
from Alumnos.models import CicloEscolar, Grado, Inscripcion, MateriaGrado
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_permisos

from .forms import CicloForm, FiltroCiclosForm


def _con_conteos(queryset):
    """Agrega a cada ciclo cuántas inscripciones activas y cuántas bajas tiene."""
    return queryset.annotate(
        inscritos=Count('inscripciones', filter=Q(inscripciones__activa=True)),
        bajas=Count('inscripciones', filter=Q(inscripciones__activa=False)),
    )


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_cicloescolar')
def ciclo_lista(request):
    filtro = FiltroCiclosForm(request.GET)
    estado = filtro.activos.get('estado', '')
    ciclos = _con_conteos(filtro.filtrar(CicloEscolar.objects.all()))
    pagina, rango_paginas, por_pagina = paginar(request, ciclos)

    hoy = timezone.localdate()
    conteos = CicloEscolar.objects.aggregate(
        total=Count('pk'),
        actual=Count('pk', filter=Q(activo=True)),
        proximo=Count('pk', filter=Q(activo=False, fecha_inicio__gt=hoy)),
        cerrado=Count('pk', filter=Q(activo=False, fecha_inicio__lte=hoy)),
    )
    # La tarjeta del ciclo en curso solo acompaña a la vista completa
    actual = None
    if not estado:
        actual = _con_conteos(CicloEscolar.objects.filter(activo=True)).order_by('-fecha_inicio').first()

    return render(request, 'ciclos/lista.html', {
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'estado': estado,
        'conteos': conteos,
        'actual': actual,
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, ciclo=None):
    return render(request, 'ciclos/form.html', {'form': form, 'ciclo': ciclo, 'es_edicion': ciclo is not None})


@requiere_permisos('Alumnos.add_cicloescolar')
def ciclo_crear(request):
    form = CicloForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            ciclo = form.save()
            messages.success(request, f'El ciclo {ciclo} fue registrado{" y es el ciclo actual" if ciclo.activo else ""}.')
            return redirect('ciclos:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@requiere_permisos('Alumnos.change_cicloescolar')
def ciclo_editar(request, pk):
    ciclo = get_object_or_404(CicloEscolar, pk=pk)
    form = CicloForm(request.POST if request.method == 'POST' else None, instance=ciclo)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, f'El ciclo {ciclo} se actualizó.')
            return redirect('ciclos:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, ciclo)


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
def _resumen_por_grado(ciclo):
    """Alumnos inscritos en cada grado del ciclo (un solo grupo por grado), en orden escolar."""
    conteos = {
        fila['grado_id']: fila
        for fila in (
            Inscripcion.objects.filter(ciclo=ciclo).values('grado_id')
            .annotate(activas=Count('pk', filter=Q(activa=True)), bajas=Count('pk', filter=Q(activa=False)))
        )
    }
    grados = Grado.objects.filter(Q(activo=True) | Q(pk__in=conteos)).academicos()
    filas = [
        {
            'grado': grado,
            'activas': conteos.get(grado.pk, {}).get('activas', 0),
            'bajas': conteos.get(grado.pk, {}).get('bajas', 0),
        }
        for grado in grados
    ]
    maximo = max((fila['activas'] for fila in filas), default=0)
    for fila in filas:
        fila['porcentaje'] = round(fila['activas'] * 100 / maximo) if maximo else 0
    return filas


@requiere_permisos('Alumnos.view_cicloescolar')
def ciclo_detalle(request, pk):
    ciclo = get_object_or_404(CicloEscolar, pk=pk)
    filas = _resumen_por_grado(ciclo)
    total_activas = sum(fila['activas'] for fila in filas)
    total_bajas = sum(fila['bajas'] for fila in filas)

    # Alumnos activos que todavía no tienen inscripción (de ningún tipo) en este ciclo
    sin_inscribir = alumnos_sin_inscribir(ciclo).count()

    # Ciclo anterior con alumnos inscritos (de ahí se reinscribe a los que siguen) y ciclo anterior con plan de
    # materias (de ahí se copian las materias y los horarios)
    origen = origen_plan = None
    if ciclo.estado != 'CERRADO':
        anteriores = CicloEscolar.objects.filter(fecha_inicio__lt=ciclo.fecha_inicio).distinct().order_by('-fecha_inicio')
        origen = anteriores.filter(inscripciones__activa=True).first()
        origen_plan = anteriores.filter(materias_grado__activa=True).first()

    return render(request, 'ciclos/detalle.html', {
        'ciclo': ciclo,
        'filas': filas,
        'total_activas': total_activas,
        'total_bajas': total_bajas,
        'sin_inscribir': sin_inscribir,
        'origen_sugerido': origen,
        'origen_plan': origen_plan,
        'materias_del_ciclo': MateriaGrado.objects.filter(ciclo=ciclo, activa=True).count(),
        'otro_actual': ciclo_actual() if not ciclo.activo else None,
    })


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.change_cicloescolar')
def ciclo_establecer_actual(request, pk):
    ciclo = get_object_or_404(CicloEscolar, pk=pk)
    if ciclo.activo:
        messages.info(request, f'El ciclo {ciclo} ya es el ciclo actual.')
        return redirect('ciclos:lista')

    anterior = ciclo_actual()
    activar_ciclo(ciclo)
    aviso = f' El ciclo {anterior} dejó de ser el actual.' if anterior else ''
    messages.success(request, f'El ciclo {ciclo} es ahora el ciclo actual.{aviso}')
    return redirect('ciclos:lista')


@require_POST
@requiere_permisos('Alumnos.change_cicloescolar')
def ciclo_cerrar(request, pk):
    """Cerrar es lógico: el ciclo deja de ser el actual, pero conserva sus inscripciones y su historial."""
    ciclo = get_object_or_404(CicloEscolar, pk=pk)
    if not ciclo.activo:
        messages.info(request, f'El ciclo {ciclo} no es el ciclo actual.')
        return redirect('ciclos:lista')

    ciclo.activo = False
    ciclo.save(update_fields=['activo'])
    messages.success(
        request,
        f'El ciclo {ciclo} se cerró. Sus inscripciones y su historial se conservan; marca otro ciclo como actual para seguir inscribiendo.',
    )
    return redirect('ciclos:lista')
