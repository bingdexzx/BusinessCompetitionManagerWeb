"""系统设置 — 流量限制配置路由。

由根路由以 path('api/', include('apps.global_.sysconfig.urls')) 引入。
"""

from django.urls import path

from apps.global_.sysconfig import views

urlpatterns = [
    path('system/rate-limit', views.RateLimitConfigView.as_view()),
    path('system/rate-limit/reset', views.RateLimitResetView.as_view()),
    path('system/rate-limit/records', views.RateLimitRecordsView.as_view()),
]
