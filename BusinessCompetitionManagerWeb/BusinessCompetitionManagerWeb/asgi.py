"""ASGI 入口（§5.1：HTTP + WebSocket，Django Channels）。

WebSocket：``/ws/notifications``（JWT 鉴权见 apps.global_.accounts.consumers）。
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.global_.accounts.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(websocket_urlpatterns),
})
