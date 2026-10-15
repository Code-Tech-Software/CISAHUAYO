"""Solo se aceptan WebSockets abiertos desde páginas del propio sistema.

ALLOWED_HOSTS es «*», así que el validador de Channels por hosts lo dejaría pasar todo: aquí el origen de la conexión
debe ser el mismo sitio que la atiende o uno de CSRF_TRUSTED_ORIGINS (el mismo criterio que los formularios).
"""
from urllib.parse import urlparse

from channels.security.websocket import WebsocketDenier
from django.conf import settings


class MismoOrigen:
    def __init__(self, aplicacion):
        self.aplicacion = aplicacion

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket' and not self.permitido(scope):
            return await WebsocketDenier()(scope, receive, send)
        return await self.aplicacion(scope, receive, send)

    @staticmethod
    def permitido(scope):
        cabeceras = dict(scope.get('headers') or [])
        origen = cabeceras.get(b'origin', b'').decode('latin1')
        host = cabeceras.get(b'host', b'').decode('latin1')
        if not origen:
            return False
        if origen in getattr(settings, 'CSRF_TRUSTED_ORIGINS', []):
            return True
        return bool(host) and urlparse(origen).netloc.lower() == host.lower()
