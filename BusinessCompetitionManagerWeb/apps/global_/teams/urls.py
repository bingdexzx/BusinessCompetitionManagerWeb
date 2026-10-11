from django.urls import path

from apps.global_.teams import views

urlpatterns = [
    path('competitions/<int:cid>/teams', views.TeamListCreateView.as_view()),
    path('competitions/<int:cid>/teams/join', views.TeamJoinView.as_view()),
    path('competitions/<int:cid>/teams/<int:tid>', views.TeamDetailView.as_view()),
    path('competitions/<int:cid>/teams/<int:tid>/join-codes', views.TeamJoinCodeView.as_view()),
    path('competitions/<int:cid>/teams/<int:tid>/industry', views.TeamIndustryAdjustView.as_view()),
]
