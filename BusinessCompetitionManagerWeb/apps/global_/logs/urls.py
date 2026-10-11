from django.urls import path

from apps.global_.logs import views

urlpatterns = [
    path('logs/network', views.NetworkLogListView.as_view()),
    path('logs/network/export', views.NetworkLogExportView.as_view()),
    path('logs/devices', views.DeviceListView.as_view()),
]
