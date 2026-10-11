"""WebSocket 路由（ASGI URLRouter 挂载）。"""

from django.urls import path

from apps.global_.accounts.consumers import NotificationConsumer

websocket_urlpatterns = [
    path('ws/notifications', NotificationConsumer.as_asgi()),
]
