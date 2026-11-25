from django.urls import path

from apps.global_.jobs import views

urlpatterns = [
    path('competitions/<int:cid>/jobs', views.JobListCreateView.as_view()),
    path('competitions/<int:cid>/jobs/<int:pk>', views.JobDetailView.as_view()),
]
