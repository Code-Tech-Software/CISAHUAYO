"""Reportes de prefectura: vista previa (con consultar), hoja para imprimir o guardar en PDF y libro de Excel (además,
con «Exportar»). Los tres usan el mismo contenido (Prefectura/reportes.py), los mismos filtros y el alcance de la cuenta."""
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.text import slugify

from CISAHUAYO.permisos import requiere_permisos
from CISAHUAYO.xlsx import libro
from Conducta.forms import FiltroForm
from Conducta.views import registros_de

from . import reportes
from .alcance import alcance_de

VER, EXPORTAR = 'Prefectura.consultar', 'Prefectura.exportar'


def _contenido(request):
    alcance = alcance_de(request.user)
    from Bitacoras.reportes import puede_incluir
    form = FiltroForm(request.GET or None, modo='reporte', alcance=alcance, reportes=reportes.TIPOS, con_bitacora=puede_incluir(request.user))
    contenido = reportes.construir(form.tipo_de_reporte, form.filtro(), request.user, alcance, registros_de(request.user))
    return form, contenido


@requiere_permisos(VER)
def reportes_vista(request):
    form, contenido = _contenido(request)
    consulta = request.GET.urlencode()
    return render(request, 'prefectura/reportes.html', {
        'seccion': 'reportes', 'filtro': form, 'contenido': contenido, 'mas_filtros': form.activos,
        'alumnos_elegidos': form.alumnos_elegidos, 'tipo': form.tipo_de_reporte,
        'puede_exportar': request.user.has_perm(EXPORTAR),
        'url_imprimir': f"{reverse('prefectura:reporte_imprimir')}?{consulta}",
        'url_pdf': f"{reverse('prefectura:reporte_imprimir')}?{consulta}{'&' if consulta else ''}pdf=1",
        'url_excel': f"{reverse('prefectura:reporte_excel')}?{consulta}",
        'url_buscar': reverse('conducta:buscar'),
    })


@requiere_permisos(VER, EXPORTAR)
def reporte_imprimir(request):
    _, contenido = _contenido(request)
    consulta = request.GET.copy()
    consulta.pop('pdf', None)
    return render(request, 'prefectura/reporte_hoja.html', {
        'contenido': contenido, 'imprimir_al_abrir': request.GET.get('pdf') == '1',
        'volver': f"{reverse('prefectura:reportes')}?{consulta.urlencode()}",
    })


@requiere_permisos(VER, EXPORTAR)
def reporte_excel(request):
    _, contenido = _contenido(request)
    datos = libro(reportes.hojas(contenido))
    nombre = f"prefectura-{slugify(contenido['subtitulo'])}-{contenido['generado']:%Y%m%d-%H%M}.xlsx"
    respuesta = HttpResponse(datos, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return respuesta
