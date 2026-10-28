"""Avisa de los comunicados programados cuya hora ya llegó (en tiempo real y push, a cada destinatario una sola vez) y
borra las imágenes del texto que nunca se enviaron. Que se vean a su hora no depende de esto (se filtra en cada
consulta) y los avisos también salen cuando alguien abre los comunicados; sirve para programarlo en un Cron de Railway,
p. ej. cada 5 minutos, y que el aviso llegue puntual aunque nadie esté usando el sistema."""
from django.core.management.base import BaseCommand

from Comunicados import avisos


class Command(BaseCommand):
    help = 'Avisa de los comunicados programados que ya llegaron a su hora de publicación.'

    def handle(self, *args, **opciones):
        publicados = avisos.publicar_pendientes()
        borradas = avisos.limpiar_imagenes()
        self.stdout.write(f'Comunicados publicados: {len(publicados)} · imágenes sin enviar borradas: {borradas}')
