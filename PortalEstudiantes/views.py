"""Portal de estudiantes (pedido del 2026-10-14): lo que ve el estudiante al entrar con su correo y su contraseña.

El acceso, la sesión y sus restricciones están en CISAHUAYO/portales.py (cada vista lleva `portal_requerido`); lo que
se muestra lo arma `resumen.py`, que también usa el portal de tutores.
"""
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from Alumnos.semanas import fecha_de
from CISAHUAYO import portales

from .resumen import resumen

TIPO = portales.ESTUDIANTE


def boletas_de_comentarios(alumno, ruta):
    """Sus boletas de comentarios publicadas, cada una con la dirección para abrirla en este portal (`ruta`)."""
    from Calificaciones.comentarios import publicadas_de
    return [{'boleta': boleta, 'url': reverse(ruta, args=[boleta.pk])} for boleta in publicadas_de(alumno)]


def hoja_de_comentarios(request, registro, volver):
    """La boleta de comentarios publicada, en la hoja para imprimir o guardar en PDF (lo que se publicó)."""
    from Calificaciones.comentarios import BoletaDeComentarios
    from Calificaciones.views_comentarios import hoja
    boleta = BoletaDeComentarios(inscripcion=registro.inscripcion, periodo=registro.periodo, materias=[], registro=registro)
    return hoja(request, [boleta], f'Boleta de comentarios · {registro.periodo.nombre}', volver)


@portales.portal_requerido(TIPO)
def inicio(request):
    from Agenda.fuentes import Persona
    from Agenda.reglas import para_el_inicio
    return render(request, 'portales/estudiantes/inicio.html', {
        **portales.contexto(request), **resumen(request.cuenta_portal, semana=fecha_de(request.GET.get('semana'))),
        **para_el_inicio(Persona(alumno=request.cuenta_portal)),   # «Próximos eventos» (2026-10-27)
        'boletas_comentarios': boletas_de_comentarios(request.cuenta_portal, 'portal_estudiantes:boleta_comentarios'),
    })


@portales.portal_requerido(TIPO)
def boleta_comentarios(request, pk):
    """Una de sus boletas de comentarios publicadas (404 si no es suya o no está publicada)."""
    from Calificaciones.models import BoletaComentarios
    registro = get_object_or_404(BoletaComentarios.objects.select_related('inscripcion__alumno', 'periodo__ciclo'),
                                 pk=pk, publicada=True, inscripcion__alumno=request.cuenta_portal)
    return hoja_de_comentarios(request, registro, f"{reverse('portal_estudiantes:inicio')}#titulo-boletas")


@require_POST
@portales.portal_requerido(TIPO)
def salir(request):
    return portales.salir(request, TIPO)
