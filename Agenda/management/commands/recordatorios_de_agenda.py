"""Manda los recordatorios de los eventos importantes de hoy y mañana (campana y notificación push), cada uno una sola
vez. No hace falta para que funcionen: también se generan cuando alguien abre la agenda o el inicio; sirve para
programarlo en un Cron de Railway (p. ej. cada hora) y que lleguen aunque nadie entre."""
from django.core.management.base import BaseCommand

from Agenda import recordatorios


class Command(BaseCommand):
    help = 'Manda los recordatorios de los eventos importantes de la agenda.'

    def handle(self, *args, **opciones):
        self.stdout.write(f'Eventos recordados: {recordatorios.generar()}')
