"""El canal de avisos de cada pestaña abierta (WebSocket en /ws/mensajes/).

Solo envía (del servidor a la pestaña): mensajes nuevos, lecturas y el total sin leer. Escribir y marcar como leído van
por peticiones normales (Mensajes/views.py), que guardan en la base de datos y luego avisan aquí.

La cuenta se toma de la sesión, igual que en las páginas: un usuario del sistema con la mensajería o la sesión de un
portal (CISAHUAYO/portales.py). Sin una de las dos, la conexión se rechaza.
"""
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .tiempo_real import grupo

registro = logging.getLogger(__name__)


class AvisosConsumer(AsyncJsonWebsocketConsumer):
    grupo = None

    async def connect(self):
        participante_id = await self._participante()
        if participante_id is None:
            await self.close(code=4403)
            return
        try:
            await self.channel_layer.group_add(grupo(participante_id), self.channel_name)
        except Exception:   # Redis caído o inalcanzable (REDIS_URL): se rechaza y la pestaña reintenta sola
            registro.exception('No se pudo unir al participante %s a sus avisos (¿Redis disponible?)', participante_id)
            await self.close(code=1011)
            return
        self.grupo = grupo(participante_id)
        await self.accept()

    async def disconnect(self, code):
        if self.grupo:
            try:
                await self.channel_layer.group_discard(self.grupo, self.channel_name)
            except Exception:
                registro.exception('No se pudo quitar al participante de sus avisos')

    async def receive_json(self, contenido, **kwargs):
        """Nada que recibir: solo responde al «ping» con el que la pestaña comprueba que la conexión sigue viva."""
        if isinstance(contenido, dict) and contenido.get('evento') == 'ping':
            await self.send_json({'evento': 'pong'})

    # --- eventos del grupo (Mensajes/tiempo_real.py) ---------------------------------------------------------------
    async def mensaje_nuevo(self, evento):
        await self.send_json({'evento': 'mensaje', **evento['datos']})

    async def mensaje_leido(self, evento):
        await self.send_json({'evento': 'leido', **evento['datos']})

    async def mensajes_resumen(self, evento):
        await self.send_json({'evento': 'resumen', **evento['datos']})

    @database_sync_to_async
    def _participante(self):
        from CISAHUAYO import portales

        from . import reglas
        usuario, sesion = self.scope.get('user'), self.scope.get('session')
        if usuario is not None and usuario.is_authenticated:
            return reglas.de_usuario(usuario).pk if reglas.usa_mensajeria(usuario) else None
        if sesion is None:
            return None
        tipo, cuenta = portales.sesion_de(sesion)
        return reglas.de_portal(tipo, cuenta).pk if cuenta is not None else None
