"""Genera los recordatorios previos de las reuniones y los avisos de acuerdos por vencer o vencidos de todo el personal y
de las familias (cada uno una sola vez). No hace falta para que funcionen: también se generan cuando cada persona abre
el sistema; sirve para programarlo, p. ej. cada hora, y que lleguen aunque nadie haya entrado."""
from django.core.management.base import BaseCommand

from Reuniones import notificaciones


class Command(BaseCommand):
    help = 'Genera los recordatorios de reuniones con familias y los avisos de acuerdos por vencer o vencidos.'

    def handle(self, *args, **opciones):
        total = notificaciones.generar_todas()
        self.stdout.write(f'Avisos nuevos: {total}')
