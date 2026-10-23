"""El canal de avisos de cada pestaña abierta (WebSocket en /ws/mensajes/).

Envía (del servidor a la pestaña): mensajes nuevos, corregidos y retirados por moderación, lecturas, «escribiendo…» y el total sin leer. Escribir y marcar como leído van
por peticiones normales (Mensajes/views.py), que guardan en la base de datos y luego avisan aquí.

La cuenta se toma de la sesión, igual que en las páginas: un usuario del sistema con la mensajería o la sesión de un
portal (CISAHUAYO/portales.py).

Por el mismo canal llegan los avisos de comunicados nuevos (Comunicados/tiempo_real.py): la pestaña se une también al
grupo de comunicados de su persona, si recibe comunicados. Un profesor que recibe comunicados pero no usa la mensajería
se conecta solo a ese grupo. Igual con las notificaciones de retiros anticipados (Retiros/tiempo_real.py): el personal
que los atiende y los tutores en su portal. Sin mensajería, comunicados ni retiros, la conexión se rechaza.
"""
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .tiempo_real import grupo

registro = logging.getLogger(__name__)


class AvisosConsumer(AsyncJsonWebsocketConsumer):
    grupos = ()
    participante_id = None
    nombre = ''
    conversaciones_propias = None   # las conversaciones en que es miembro (para «escribiendo…»), al primer aviso

    async def connect(self):
        participante_id, de_comunicados, de_retiros, de_reuniones = await self._participante()
        self.participante_id = participante_id
        if participante_id is None and not de_comunicados and not de_retiros and not de_reuniones:
            await self.close(code=4403)
            return
        grupos = ([grupo(participante_id)] if participante_id is not None else []) + [g for g in (de_comunicados, de_retiros, de_reuniones) if g]
        try:
            for nombre in grupos:
                await self.channel_layer.group_add(nombre, self.channel_name)
        except Exception:   # Redis caído o inalcanzable (REDIS_URL): se rechaza y la pestaña reintenta sola
            registro.exception('No se pudo unir a sus avisos a %s (¿Redis disponible?)', participante_id or de_comunicados)
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
        """Responde al «ping» con el que la pestaña comprueba que la conexión sigue viva y reenvía «escribiendo…» a la
        otra persona de la conversación (solo si quien escribe es miembro de ella; no se guarda nada)."""
        if not isinstance(contenido, dict):
            return
        if contenido.get('evento') == 'ping':
            await self.send_json({'evento': 'pong'})
        elif contenido.get('evento') == 'escribiendo' and self.participante_id is not None:
            conversacion = contenido.get('conversacion')
            if isinstance(conversacion, int):
                await self._avisar_escribiendo(conversacion)

    @database_sync_to_async
    def _avisar_escribiendo(self, conversacion):
        from .models import Miembro, Participante
        from .tiempo_real import avisar_escribiendo
        if self.conversaciones_propias is None:
            self.conversaciones_propias = set(Miembro.objects.filter(participante=self.participante_id).values_list('conversacion_id', flat=True))
            self.nombre = Participante.objects.select_related('usuario', 'alumno', 'tutor').get(pk=self.participante_id).nombre
        if conversacion not in self.conversaciones_propias:
            # Una conversación recién empezada en otra pestaña: se vuelve a consultar una sola vez
            if not Miembro.objects.filter(participante=self.participante_id, conversacion=conversacion).exists():
                return
            self.conversaciones_propias.add(conversacion)
        avisar_escribiendo(conversacion, self.participante_id, self.nombre)

    # --- eventos del grupo (Mensajes/tiempo_real.py) ---------------------------------------------------------------
    async def mensaje_nuevo(self, evento):
        await self.send_json({'evento': 'mensaje', **evento['datos']})

    async def mensaje_retirado(self, evento):
        await self.send_json({'evento': 'retirado', **evento['datos']})

    async def mensaje_editado(self, evento):
        await self.send_json({'evento': 'editado', **evento['datos']})

    async def mensaje_escribiendo(self, evento):
        await self.send_json({'evento': 'escribiendo', **evento['datos']})

    async def mensaje_leido(self, evento):
        await self.send_json({'evento': 'leido', **evento['datos']})

    async def mensajes_resumen(self, evento):
        await self.send_json({'evento': 'resumen', **evento['datos']})

    async def comunicado_nuevo(self, evento):
        await self.send_json({'evento': 'comunicado', **evento['datos']})

    async def retiro_aviso(self, evento):
        await self.send_json({'evento': 'retiro', **evento['datos']})

    async def reunion_aviso(self, evento):
        await self.send_json({'evento': 'reunion', **evento['datos']})

    @database_sync_to_async
    def _participante(self):
        """(id del participante o None, grupo de comunicados de la persona o None, grupo de retiros o None, grupo de
        reuniones con familias o None)."""
        from CISAHUAYO import portales

        from . import reglas
        usuario, sesion = self.scope.get('user'), self.scope.get('session')
        if usuario is not None and usuario.is_authenticated:
            participante = reglas.de_usuario(usuario).pk if reglas.usa_mensajeria(usuario) else None
            return participante, self._de_comunicados(usuario=usuario), self._de_retiros(usuario=usuario), self._de_reuniones(usuario=usuario)
        if sesion is None:
            return None, None, None, None
        tipo, cuenta = portales.sesion_de(sesion)
        if cuenta is None:
            return None, None, None, None
        de_retiros = self._de_retiros(tutor=cuenta) if tipo == portales.TUTOR else None
        de_reuniones = self._de_reuniones(tutor=cuenta) if tipo == portales.TUTOR else None
        return reglas.de_portal(tipo, cuenta).pk, self._de_comunicados(tipo=tipo, cuenta=cuenta), de_retiros, de_reuniones

    @staticmethod
    def _de_retiros(usuario=None, tutor=None):
        """Si falla (p. ej. sin la migración de Retiros), lo demás sigue igual: solo no llegan esos avisos."""
        try:
            from Retiros import tiempo_real
            return tiempo_real.grupo_de_usuario(usuario) if usuario is not None else tiempo_real.grupo_de_tutor(tutor)
        except Exception:
            registro.exception('No se pudo preparar el aviso de retiros')
            return None

    @staticmethod
    def _de_reuniones(usuario=None, tutor=None):
        """Si falla (p. ej. sin la migración de Reuniones), lo demás sigue igual: solo no llegan esos avisos."""
        try:
            from Reuniones import tiempo_real
            return tiempo_real.grupo_de_usuario(usuario) if usuario is not None else tiempo_real.grupo_de_tutor(tutor)
        except Exception:
            registro.exception('No se pudo preparar el aviso de reuniones')
            return None

    @staticmethod
    def _de_comunicados(usuario=None, tipo=None, cuenta=None):
        """Si falla (p. ej. sin la migración de Comunicados), la mensajería sigue igual: solo no llegan esos avisos."""
        try:
            from Comunicados import tiempo_real
            return tiempo_real.grupo_de_usuario(usuario) if usuario is not None else tiempo_real.grupo_de_portal(tipo, cuenta)
        except Exception:
            registro.exception('No se pudo preparar el aviso de comunicados')
            return None
