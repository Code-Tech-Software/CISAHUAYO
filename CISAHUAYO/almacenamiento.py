"""Almacenamiento de los archivos estáticos (CSS, JavaScript, iconos).

En producción (DEBUG = False) es el de WhiteNoise con manifiesto: cada archivo se publica con un hash en el nombre
(`app.3f2a….js`), así que al cambiar el archivo cambia su URL y el navegador nunca usa una copia vieja.

En desarrollo (DEBUG = True) el manifiesto no se usa y la URL siempre es la misma (`/static/js/app.js`): si el
navegador guardó una copia, podía seguir usándola aunque el archivo ya hubiera cambiado (pasó con el menú lateral: el
HTML nuevo con un `app.js` viejo que no sabía desplegar los grupos, y un sprite de iconos sin el icono nuevo). Por eso
aquí se agrega `?v=<fecha de modificación>`: cada cambio del archivo es una URL nueva.
"""
import os

from django.conf import settings
from django.contrib.staticfiles import finders
from whitenoise.storage import CompressedManifestStaticFilesStorage


class EstaticosConVersion(CompressedManifestStaticFilesStorage):
    def url(self, name, force=False):
        url = super().url(name, force)
        if settings.DEBUG and not force:
            ruta = finders.find(name.split('?')[0].split('#')[0])
            if ruta and not isinstance(ruta, list):
                url = f'{url}{"&" if "?" in url else "?"}v={int(os.path.getmtime(ruta))}'
        return url
