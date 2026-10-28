"""Los comunicados con evento en la agenda (pedido del 2026-10-27): un comunicado que anuncia algo con fecha (una junta,
una excursión) aparece en el calendario de quien lo recibe (y de quien lo envió), con su propio color y su enlace al
comunicado. No es un evento de la agenda: no se edita aquí ni depende de Agenda.gestionar; lo que se ve sale de
Comunicados/reglas.eventos_para_la_agenda (los que esa persona puede ver).
"""
import logging
from dataclasses import dataclass

from django.urls import reverse
from django.utils.formats import date_format

registro = logging.getLogger(__name__)
COLOR, COLOR_TEXTO = '#2f737c', '#FFFFFF'   # el turquesa del sistema, con texto blanco (5.5:1)
NOMBRE = 'Comunicado'


@dataclass
class EventoDeComunicado:
    """Un comunicado con evento, con lo mismo que el calendario usa de un EventoAgenda."""
    comunicado: object
    url_propia: str

    @property
    def pk(self):
        return -self.comunicado.pk   # negativo: no se confunde con los eventos de la agenda

    @property
    def titulo(self):
        return self.comunicado.titulo

    @property
    def descripcion(self):
        texto = ' '.join(self.comunicado.descripcion.split())
        return texto if len(texto) <= 400 else texto[:399].rstrip() + '…'

    @property
    def fecha_inicio(self):
        return self.comunicado.evento_fecha

    fecha_fin = fecha_inicio

    @property
    def todo_el_dia(self):
        return self.comunicado.evento_hora_inicio is None

    @property
    def hora_inicio(self):
        return self.comunicado.evento_hora_inicio

    @property
    def lugar(self):
        return self.comunicado.evento_lugar

    color, color_texto, nombre_alcance, es_del_colegio, varios_dias = COLOR, COLOR_TEXTO, NOMBRE, False, False

    @property
    def texto_de_fechas(self):
        return date_format(self.fecha_inicio, 'l j \\d\\e F \\d\\e Y').capitalize()

    @property
    def texto_de_horario(self):
        inicio, fin = self.comunicado.evento_hora_inicio, self.comunicado.evento_hora_fin
        if inicio is None:
            return 'Todo el día'
        return f'{inicio:%H:%M} a {fin:%H:%M}' if fin else f'Desde las {inicio:%H:%M}'

    @property
    def hora_corta(self):
        return '' if self.todo_el_dia else f'{self.hora_inicio:%H:%M}'

    def como_dato(self):
        """Sus datos para static/js/agenda.js: al tocarlo no abre la ventana de la agenda, lleva al comunicado."""
        return {'id': self.pk, 'titulo': self.titulo, 'descripcion': self.descripcion, 'alcance': NOMBRE, 'color': COLOR,
                'colorTexto': COLOR_TEXTO, 'fechas': self.texto_de_fechas, 'horario': self.texto_de_horario, 'lugar': self.lugar,
                'detalle': self.url_propia, 'comunicado': True}


def eventos_de_comunicados(request, desde, hasta):
    """Los comunicados con evento entre esas fechas de quien mira la agenda: en el sistema, los que recibe (un profesor o
    el personal) y los que envió; en un portal, los que recibe. Si algo falla (p. ej. sin la migración de Comunicados),
    la agenda sigue igual, sin ellos."""
    try:
        from Comunicados import reglas
        from Comunicados.alcance import SEGUIMIENTO
        from Comunicados.views import ESPACIO_DE_PORTAL
        usuario = getattr(request, 'user', None)
        if usuario is not None and usuario.is_authenticated:
            lector = reglas.lector_de_usuario(usuario)
            autor = usuario if usuario.has_perm(SEGUIMIENTO) else None
            espacio = 'comunicados'
        else:
            cuenta = getattr(request, 'cuenta_portal', None)
            if cuenta is None:
                return []
            lector, autor = reglas.lector_de_portal(request.cuenta_portal_tipo, cuenta), None
            espacio = ESPACIO_DE_PORTAL[request.cuenta_portal_tipo]
        eventos = []
        for comunicado, recibido in reglas.eventos_para_la_agenda(lector, autor, desde, hasta):
            url = reverse(f'{espacio}:recibido', args=[comunicado.pk]) if recibido else reverse('comunicados:detalle', args=[comunicado.pk])
            eventos.append(EventoDeComunicado(comunicado, url))
        return eventos
    except Exception:
        registro.exception('No se pudieron agregar los comunicados a la agenda')
        return []
