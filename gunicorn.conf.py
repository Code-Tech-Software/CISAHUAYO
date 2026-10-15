"""Configuración de gunicorn (gunicorn la lee sola desde la raíz del proyecto).

La mensajería en tiempo real usa WebSockets, que solo atiende la aplicación ASGI (CISAHUAYO/asgi.py). Lo ideal es
iniciar con daphne (Procfile, railway.toml), pero si Railway arranca con su comando de Django, `gunicorn CISAHUAYO.wsgi`
(lo decide el panel o el detector de Railway), con este archivo gunicorn sirve de todos modos la aplicación ASGI con su
propio worker ASGI, que atiende HTTP y WebSockets. Sin él, gunicorn sirve la aplicación WSGI y /ws/mensajes/ da 404.
"""
APLICACION_ASGI = 'CISAHUAYO.asgi:application'

# El worker ASGI de gunicorn (asyncio): HTTP/1.1 y WebSockets
worker_class = 'asgi'
# Channels no atiende el ciclo de vida ASGI («lifespan»): no hace falta y evita un aviso al arrancar
asgi_lifespan = 'off'
# Detrás del proxy de Railway: confía en sus encabezados (HTTPS y la IP real), como daphne con --proxy-headers
forwarded_allow_ips = '*'


def on_starting(server):
    """Antes de crear los workers: la aplicación que cargan es la ASGI, aunque el comando haya dicho la WSGI."""
    if getattr(server.app, 'app_uri', None) != APLICACION_ASGI:
        server.log.info('Se sirve %s (ASGI, con WebSockets) en lugar de %s', APLICACION_ASGI, server.app.app_uri)
        server.app.app_uri = APLICACION_ASGI
