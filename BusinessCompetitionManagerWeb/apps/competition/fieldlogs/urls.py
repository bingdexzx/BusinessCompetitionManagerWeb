from django.urls import path

from apps.competition.fieldlogs import views

urlpatterns = [
    path('competitions/<int:cid>/logs/fields', views.FieldLogListView.as_view()),
    path('competitions/<int:cid>/logs/fields/export', views.FieldLogExportView.as_view()),
]
