"""«Mi horario»: lo que el perfil Docente consulta en Horarios (pedido del 2026-10-30; las reglas de acceso, en alcance.py).

Es una semana real del calendario: cada nivel con su semana A o B y la versión del horario de esas fechas (Alumnos/semanas.py),
solo con los bloques de sus asignaciones, sin recesos. Los filtros salen de esas mismas asignaciones (FiltroMiHorarioForm).
Se imprime desde esta misma página, así que la hoja lleva el mismo alcance.
"""
from django.shortcuts import redirect, render
from django.utils import timezone

from Alumnos.academico import ciclo_editable, elegir_ciclo
from Alumnos.horarios import cuadricula, duracion, formatear_duracion
from Alumnos.models import ORDEN_NIVELES, DiaNoLectivo, Grado
from Alumnos.semanas import TODAS, Calendario, Semana, bloques_de_semana, fecha_de, lunes_de
from CISAHUAYO.permisos import requiere_permisos

from .alcance import asignaciones_del_docente, ciclos_del_docente, solo_sus_clases
from .forms import FiltroMiHorarioForm


def _dias_sin_clases(semana, niveles):
    """[(fecha, motivo, niveles)] de esa semana, en los niveles en que da clases."""
    dias = {}
    for dia in DiaNoLectivo.objects.filter(fecha__range=(semana.lunes, semana.domingo), nivel__in=niveles).order_by('fecha', 'motivo'):
        dias.setdefault((dia.fecha, dia.motivo), []).append(dia.get_nivel_display())
    return [(fecha, motivo, ', '.join(nombres)) for (fecha, motivo), nombres in dias.items()]


@requiere_permisos('Alumnos.view_horariomateria')
def mi_horario(request):
    if not solo_sus_clases(request.user):
        return redirect('horarios:lista')
    ciclos = ciclos_del_docente(request.user)
    ciclo = elegir_ciclo(request.GET.get('ciclo', ''), ciclos)
    hoy = timezone.localdate()
    filtro = FiltroMiHorarioForm(request.GET, asignaciones=asignaciones_del_docente(request.user, ciclo), ciclo=ciclo, hoy=hoy)

    calendario = Calendario(ciclo)
    fecha = min(max(fecha_de(request.GET.get('fecha')) or hoy, filtro.desde), filtro.hasta)
    semana = Semana(TODAS, lunes_de(fecha))
    bloques = list(
        bloques_de_semana(fecha, ciclo, calendario, materia_grado__in=filtro.elegidas)
        .select_related('materia_grado__materia', 'materia_grado__grado', 'materia_grado__grupo__nombre', 'materia_grado__grupo__grado')
    ) if filtro.elegidas else []
    niveles = [nivel for nivel in ORDEN_NIVELES if any(a.grado.nivel == nivel for a in filtro.elegidas)]
    minutos = sum(duracion(bloque) for bloque in bloques)

    return render(request, 'horarios/mi_horario.html', {
        'ciclos': ciclos,
        'ciclo': ciclo,
        'editable': ciclo_editable(ciclo),
        'filtro': filtro,
        'semana': semana,
        'fecha': fecha,
        'desde': filtro.desde,
        'hasta': filtro.hasta,
        'puede_anterior': semana.lunes > filtro.desde,
        'puede_siguiente': semana.siguiente <= filtro.hasta,
        'esta_semana': hoy if filtro.desde <= hoy <= filtro.hasta and lunes_de(hoy) != semana.lunes else None,
        'semanas_por_nivel': [(dict(Grado.NIVEL_CHOICES)[nivel], calendario.info(fecha, nivel)) for nivel in niveles if calendario.alternado(nivel)],
        'sin_clases': _dias_sin_clases(semana, niveles) if niveles else [],
        'bloques': bloques,
        'cuadricula': cuadricula(bloques),
        'etiqueta_horario': f'Mi horario de la semana del {semana.rango}',
        'total_materias': len({bloque.materia_grado.materia_id for bloque in bloques}),
        'total_grupos': len({bloque.materia_grado.grupo_id for bloque in bloques}),
        'horas_semanales': formatear_duracion(minutos) if minutos else '',
    })
