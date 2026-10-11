from django.urls import path

from apps.global_.memberships import views

urlpatterns = [
    path('competitions/<int:cid>/members', views.MemberListCreateView.as_view()),
    path('competitions/<int:cid>/members/<int:mid>', views.MemberDetailView.as_view()),
]
