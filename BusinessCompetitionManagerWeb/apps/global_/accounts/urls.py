from django.urls import path

from apps.global_.accounts import views

urlpatterns = [
    path('auth/register', views.RegisterView.as_view()),
    path('auth/login', views.LoginView.as_view()),
    path('auth/refresh', views.GipfelTokenRefreshView.as_view()),
    path('auth/change-password', views.ChangePasswordView.as_view()),
    path('me', views.MeView.as_view()),
    path('me/devices', views.MyDevicesView.as_view()),
    path('version', views.VersionView.as_view()),
    path('update-logs', views.UpdateLogListView.as_view()),
    path('update-logs/latest', views.UpdateLogLatestView.as_view()),
    path('update-logs/<int:pk>/read', views.UpdateLogReadView.as_view()),
]
