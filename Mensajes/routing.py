from django.urls import path

from .consumers import AvisosConsumer

websocket_urlpatterns = [
    path('ws/mensajes/', AvisosConsumer.as_asgi()),
]
