from django.urls import path

from apps.global_.schools.views import SchoolDetailView, SchoolListCreateView

urlpatterns = [
    path('schools', SchoolListCreateView.as_view()),
    path('schools/<int:pk>', SchoolDetailView.as_view()),
]
