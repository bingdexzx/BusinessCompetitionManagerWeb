from django.urls import path

from apps.global_.competitions import views

urlpatterns = [
    path('competitions', views.CompetitionListCreateView.as_view()),
    path('competitions/<int:cid>', views.CompetitionDetailView.as_view()),
    path('competitions/<int:cid>/meta', views.CompetitionMetaView.as_view()),
    path('competitions/<int:cid>/transition', views.CompetitionTransitionView.as_view()),
]
