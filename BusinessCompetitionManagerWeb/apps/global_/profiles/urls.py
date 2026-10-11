from django.urls import path

from apps.global_.profiles import views

urlpatterns = [
    path('me/awards', views.MyAwardsView.as_view()),
    path('me/medals', views.MedalListView.as_view()),
    path('me/medals/<int:mid>', views.MedalDetailView.as_view()),
    path('medals', views.MedalManageView.as_view()),
]
