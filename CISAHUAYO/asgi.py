"""
Configuración ASGI de CISAHUAYO (servidor: daphne, ver Procfile).

Las peticiones HTTP van a Django como siempre; los WebSockets (los avisos en tiempo real de la mensajería, Mensajes/)
pasan por la sesión y la autenticación de Django para saber de quién son, y solo se aceptan desde el propio sitio.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CISAHUAYO.settings')

# Django se inicia antes de importar lo que usa modelos
aplicacion_http = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from Mensajes.routing import websocket_urlpatterns  # noqa: E402
from Mensajes.seguridad import MismoOrigen  # noqa: E402

application = ProtocolTypeRouter({
    'http': aplicacion_http,
    'websocket': MismoOrigen(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
})
