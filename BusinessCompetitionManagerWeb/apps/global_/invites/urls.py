from django.urls import path

from apps.global_.invites import views

urlpatterns = [
    path('competitions/<int:cid>/invites', views.InviteListCreateView.as_view()),
    path('invites/redeem', views.InviteRedeemView.as_view()),
]
