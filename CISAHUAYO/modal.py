"""Formularios en ventanas modales.

Las páginas de alta y edición siguen existiendo (funcionan sin JavaScript y se pueden abrir en otra pestaña), pero
`static/js/modal-form.js` las abre dentro de una ventana: pide la página con fetch, muestra su formulario y lo envía
también con fetch. Eso necesita un único ajuste del servidor, que vive aquí: cuando la petición lleva la cabecera
`X-Modal-Form`, una redirección (formulario guardado, sesión vencida...) se devuelve como JSON `{"redirect": "..."}`
en lugar de seguirla. Así el navegador no descarga la página de destino por debajo y los mensajes de confirmación
siguen guardados para mostrarse cuando la página navegue ahí.
"""
from django.http import JsonResponse

ENCABEZADO = 'X-Modal-Form'
REDIRECCIONES = (301, 302, 303, 307, 308)


class FormularioModalMiddleware:
    """Debe ir después de MessageMiddleware en MIDDLEWARE: así los mensajes quedan guardados en la respuesta final."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        respuesta = self.get_response(request)
        if request.headers.get(ENCABEZADO) and respuesta.status_code in REDIRECCIONES:
            convertida = JsonResponse({'redirect': respuesta['Location']})
            convertida['Cache-Control'] = 'no-store'
            for nombre, galleta in respuesta.cookies.items():
                convertida.cookies[nombre] = galleta
            return convertida
        return respuesta
