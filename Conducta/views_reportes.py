"""Reportes de conducta (Gestión académica): vista previa, hoja para imprimir o guardar en PDF y libro de Excel, con
los mismos filtros y el mismo contenido (Conducta/reportes.py)."""
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.text import slugify

from CISAHUAYO.permisos import requiere_permisos
from CISAHUAYO.xlsx import libro
from Prefectura.alcance import alcance_de

from . import reportes
from .forms import FiltroForm, TiposDeReporte
from .permisos import VER


def _contenido(request):
    from .views import registros_de
    from Bitacoras.reportes import puede_incluir
    form = FiltroForm(request.GET or None, modo='reporte', alcance=alcance_de(request.user), con_bitacora=puede_incluir(request.user))
    return form, reportes.construir(form.tipo_de_reporte, form.filtro(), request.user, registros=registros_de(request.user))


@requiere_permisos(VER)
def reportes_vista(request):
    form, contenido = _contenido(request)
    consulta = request.GET.urlencode()
    return render(request, 'conducta/reportes.html', {
        'seccion': 'reportes', 'filtro': form, 'contenido': contenido, 'mas_filtros': form.activos,
        'alumnos_elegidos': form.alumnos_elegidos, 'tipos': TiposDeReporte.REPORTES, 'tipo': form.tipo_de_reporte,
        'url_imprimir': f"{reverse('conducta:reporte_imprimir')}?{consulta}",
        'url_pdf': f"{reverse('conducta:reporte_imprimir')}?{consulta}{'&' if consulta else ''}pdf=1",
        'url_excel': f"{reverse('conducta:reporte_excel')}?{consulta}",
        'url_buscar': reverse('conducta:buscar'),
    })


@requiere_permisos(VER)
def reporte_imprimir(request):
    _, contenido = _contenido(request)
    consulta = request.GET.copy()
    consulta.pop('pdf', None)
    return render(request, 'conducta/reporte_hoja.html', {
        'contenido': contenido, 'imprimir_al_abrir': request.GET.get('pdf') == '1',
        'volver': f"{reverse('conducta:reportes')}?{consulta.urlencode()}",
    })


@requiere_permisos(VER)
def reporte_excel(request):
    _, contenido = _contenido(request)
    datos = libro(reportes.hojas(contenido))
    nombre = f"conducta-{slugify(contenido['subtitulo'])}-{contenido['generado']:%Y%m%d-%H%M}.xlsx"
    respuesta = HttpResponse(datos, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return respuesta
