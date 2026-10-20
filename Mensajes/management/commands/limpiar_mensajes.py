"""Borra las imágenes y los documentos que se subieron a una conversación y nunca se enviaron (de hace más de un día).
No hace falta para que funcione: la mensajería lo hace sola una vez al día; sirve para programarlo en el servidor."""
from django.core.management.base import BaseCommand

from Mensajes import limpieza


class Command(BaseCommand):
    help = 'Borra los archivos de la mensajería que se subieron y nunca se enviaron (de hace más de un día).'

    def handle(self, *args, **opciones):
        total = limpieza.limpiar_pendientes()
        self.stdout.write(f'Archivos sin enviar borrados: {total}')
