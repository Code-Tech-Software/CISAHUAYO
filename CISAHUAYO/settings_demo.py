"""Ajustes de la base de demostración (pedido del 2026-11-09): el sistema completo sobre `demo.sqlite3`, en la carpeta
del proyecto, con datos ficticios que llena `python manage.py sembrar_demo`.

Se usan con `--settings=CISAHUAYO.settings_demo` y nunca tocan nada de producción aunque el `.env` lo tenga:
- La base es el archivo `demo.sqlite3` (no la de DATABASE_URL).
- Los archivos subidos (comprobantes, adjuntos, fotos) van a la carpeta `demo_media/` (no a Cloudinary).
- Sin Redis (la mensajería en tiempo real queda en memoria), sin notificaciones push y sin hilos en segundo plano: con
  SQLite, todo en la misma petición evita bloqueos.
- Los estáticos se sirven tal cual (no hace falta `collectstatic`).
"""
import os

# Antes de leer los ajustes generales: lo que trae el `.env` no se usa (load_dotenv no sobrescribe lo que ya existe)
for _clave in ('DATABASE_URL', 'REDIS_URL', 'CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET',
               'VAPID_PUBLIC_KEY', 'VAPID_PRIVATE_KEY'):
    os.environ[_clave] = ''

from .settings import *  # noqa: E402,F401,F403
from .settings import BASE_DIR  # noqa: E402

DEMO = True
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']
CSRF_TRUSTED_ORIGINS = ['http://localhost:8000', 'http://127.0.0.1:8000']

# WAL: el servidor de la demostración lee mientras escribe sin bloquearse, y llenar la base es más rápido
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'demo.sqlite3',
                         'OPTIONS': {'timeout': 30, 'init_command': 'PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;'}}}

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
MEDIA_ROOT = BASE_DIR / 'demo_media'
MEDIA_URL = '/media/'

CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
VAPID_PUBLIC_KEY = VAPID_PRIVATE_KEY = ''
ASISTENCIA_CIERRE_EN_SEGUNDO_PLANO = False
PUSH_EN_SEGUNDO_PLANO = False
COMUNICADOS_EN_SEGUNDO_PLANO = False
AGENDA_EN_SEGUNDO_PLANO = False
