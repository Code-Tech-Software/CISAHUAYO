"""Ayudantes para las acciones que reciben datos de un formulario y vuelven a la página de origen."""
from django.utils.http import url_has_allowed_host_and_scheme


def destino_seguro(request, por_defecto):
    """A dónde volver tras una acción: el `next` del formulario si es una dirección de este sitio."""
    destino = request.POST.get('next', '')
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return destino
    return por_defecto


def solo_numeros(valores):
    """Los valores de la lista que son números enteros (los demás se descartan)."""
    return [int(valor) for valor in valores if str(valor).isdigit()]
