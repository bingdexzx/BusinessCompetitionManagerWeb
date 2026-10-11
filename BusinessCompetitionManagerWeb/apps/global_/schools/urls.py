from django.urls import path

from apps.global_.schools.views import SchoolListCreateView

urlpatterns = [
    path('schools', SchoolListCreateView.as_view()),
]
