"""Portal de tutores (pedido del 2026-10-14): lo que ve el tutor al entrar con su usuario y su contraseña.

Solo ve a los estudiantes con los que tiene un vínculo activo (TutorAlumno.activo); de cada uno, lo mismo que ve el
estudiante en su portal (PortalEstudiantes/resumen.py). El acceso y la sesión están en CISAHUAYO/portales.py.
"""
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from Alumnos.models import NotificacionAsistencia, TutorAlumno
from Alumnos.semanas import fecha_de
from Asistencias.context_processors import pendientes_de
from CISAHUAYO import portales
from PortalEstudiantes.resumen import resumen

TIPO = portales.TUTOR


def _vinculos(tutor):
    return TutorAlumno.objects.filter(tutor=tutor, activo=True).select_related('alumno')


@portales.portal_requerido(TIPO)
def inicio(request):
    vinculos = _vinculos(request.cuenta_portal).order_by('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')
    return render(request, 'portales/tutores/inicio.html', {
        **portales.contexto(request),
        'estudiantes': [{'vinculo': vinculo, **resumen(vinculo.alumno, completo=False)} for vinculo in vinculos],
    })


@portales.portal_requerido(TIPO)
def estudiante(request, pk):
    """Horario, asistencia y calificaciones de uno de sus estudiantes (404 si no está vinculado con él)."""
    vinculo = get_object_or_404(_vinculos(request.cuenta_portal), alumno_id=pk)
    # Al abrir a su estudiante, sus avisos de asistencia (faltas y retardos) quedan leídos
    pendientes_de(request.cuenta_portal).filter(inscripcion__alumno_id=pk).update(leida=True)
    return render(request, 'portales/tutores/estudiante.html', {
        **portales.contexto(request), **resumen(vinculo.alumno, semana=fecha_de(request.GET.get('semana'))), 'vinculo': vinculo,
    })


@portales.portal_requerido(TIPO)
def aviso_asistencia(request, pk):
    """Abre un aviso de asistencia de la campana: lleva a su estudiante (ahí queda leído). 404 si el aviso no es suyo."""
    aviso = get_object_or_404(NotificacionAsistencia.objects.select_related('inscripcion'), pk=pk, tutor=request.cuenta_portal)
    return redirect('portal_tutores:estudiante', pk=aviso.inscripcion.alumno_id)


@require_POST
@portales.portal_requerido(TIPO)
def salir(request):
    return portales.salir(request, TIPO)
