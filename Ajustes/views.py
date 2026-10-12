from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from CISAHUAYO import temas
from Usuarios.models import PerfilUsuario

from .forms import AparienciaForm


def _es_fetch(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


@login_required
def ajustes(request):
    """Apariencia: cada persona elige su tema de color y cómo se ve el menú lateral (se guarda en su perfil, así la
    sigue en cualquier equipo). El modo claro u oscuro es de cada dispositivo y lo recuerda el navegador.

    Con JavaScript cada cambio se aplica y se guarda al momento (responde JSON); sin él, con el botón «Guardar»."""
    perfil = PerfilUsuario.de(request.user)
    form = AparienciaForm(request.POST if request.method == 'POST' else None, instance=perfil)
    if request.method == 'POST':
        if form.is_valid():
            perfil = form.save()
            tema = temas.tema(perfil.tema)
            mensaje = f'Listo: ahora usas el tema {tema["nombre"]}.'
            if _es_fetch(request):
                return JsonResponse({'ok': True, 'mensaje': mensaje, 'tema': tema['clave'], 'color': tema['color'], 'menu': perfil.menu_lateral})
            messages.success(request, mensaje)
            return redirect('ajustes:inicio')
        if _es_fetch(request):
            errores = [error for lista in form.errors.values() for error in lista]
            return JsonResponse({'ok': False, 'mensaje': ' '.join(errores)}, status=400)
        messages.error(request, 'No se pudo guardar: revisa lo marcado.')
    return render(request, 'ajustes/apariencia.html', {'form': form, 'todas_las_fuentes': temas.url_de_todas_las_fuentes()})
