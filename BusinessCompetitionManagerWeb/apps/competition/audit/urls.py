from django.urls import path

from apps.competition.audit import views

urlpatterns = [
    path('competitions/<int:cid>/audit-logs', views.AuditLogListView.as_view()),
]
