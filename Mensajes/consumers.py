"""El canal de avisos de cada pestaña abierta (WebSocket en /ws/mensajes/).

Solo envía (del servidor a la pestaña): mensajes nuevos, lecturas y el total sin leer. Escribir y marcar como leído van
por peticiones normales (Mensajes/views.py), que guardan en la base de datos y luego avisan aquí.

La cuenta se toma de la sesión, igual que en las páginas: un usuario del sistema con la mensajería o la sesión de un
portal (CISAHUAYO/portales.py). Sin una de las dos, la conexión se rechaza.

Por el mismo canal llegan los avisos de comunicados nuevos (Comunicados/tiempo_real.py): la pestaña se une también al
grupo de comunicados de su persona, si recibe comunicados.
"""
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .tiempo_real import grupo

registro = logging.getLogger(__name__)


class AvisosConsumer(AsyncJsonWebsocketConsumer):
    grupos = ()

    async def connect(self):
        participante_id, de_comunicados = await self._participante()
        if participante_id is None:
            await self.close(code=4403)
            return
        grupos = [grupo(participante_id)] + ([de_comunicados] if de_comunicados else [])
        try:
            for nombre in grupos:
                await self.channel_layer.group_add(nombre, self.channel_name)
        except Exception:   # Redis caído o inalcanzable (REDIS_URL): se rechaza y la pestaña reintenta sola
            registro.exception('No se pudo unir al participante %s a sus avisos (¿Redis disponible?)', participante_id)
            await self.close(code=1011)
            return
        self.grupos = grupos
        await self.accept()

    async def disconnect(self, code):
        for nombre in self.grupos:
            try:
                await self.channel_layer.group_discard(nombre, self.channel_name)
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

    async def comunicado_nuevo(self, evento):
        await self.send_json({'evento': 'comunicado', **evento['datos']})

    @database_sync_to_async
    def _participante(self):
        """(id del participante o None, grupo de comunicados de la persona o None)."""
        from CISAHUAYO import portales

        from . import reglas
        usuario, sesion = self.scope.get('user'), self.scope.get('session')
        if usuario is not None and usuario.is_authenticated:
            if not reglas.usa_mensajeria(usuario):
                return None, None
            return reglas.de_usuario(usuario).pk, self._de_comunicados(usuario=usuario)
        if sesion is None:
            return None, None
        tipo, cuenta = portales.sesion_de(sesion)
        if cuenta is None:
            return None, None
        return reglas.de_portal(tipo, cuenta).pk, self._de_comunicados(tipo=tipo, cuenta=cuenta)

    @staticmethod
    def _de_comunicados(usuario=None, tipo=None, cuenta=None):
        """Si falla (p. ej. sin la migración de Comunicados), la mensajería sigue igual: solo no llegan esos avisos."""
        try:
            from Comunicados import tiempo_real
            return tiempo_real.grupo_de_usuario(usuario) if usuario is not None else tiempo_real.grupo_de_portal(tipo, cuenta)
        except Exception:
            registro.exception('No se pudo preparar el aviso de comunicados')
            return None
