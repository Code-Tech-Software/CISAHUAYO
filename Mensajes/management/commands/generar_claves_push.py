"""Genera el par de claves (VAPID) de las notificaciones push de la mensajería (Mensajes/push.py).

Se corre una sola vez y las dos líneas que imprime van en las variables de entorno del servidor (Railway) y en el .env
local. Si se cambian después, los navegadores ya suscritos tendrán que volver a activar los avisos.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b'=').decode()


class Command(BaseCommand):
    help = 'Genera las claves VAPID de las notificaciones push (van en VAPID_PUBLIC_KEY y VAPID_PRIVATE_KEY).'

    def handle(self, *args, **opciones):
        privada = ec.generate_private_key(ec.SECP256R1())
        publica = privada.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.stdout.write(f'VAPID_PUBLIC_KEY={_b64(publica)}')
        self.stdout.write(f'VAPID_PRIVATE_KEY={_b64(privada.private_numbers().private_value.to_bytes(32, "big"))}')
        self.stdout.write(self.style.WARNING('Guárdalas en las variables de entorno (Railway y .env). La privada no se comparte.'))
