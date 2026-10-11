from django.urls import path

from apps.competition.fiscal import views

urlpatterns = [
    path('competitions/<int:cid>/fiscal-years', views.FiscalYearListView.as_view()),
    path('competitions/<int:cid>/fiscal-years/open', views.FiscalYearOpenView.as_view()),
    path('competitions/<int:cid>/fiscal-years/close', views.FiscalYearCloseView.as_view()),
    path('competitions/<int:cid>/fiscal-years/<int:fy_id>/backups',
         views.FiscalYearBackupListView.as_view()),
]
