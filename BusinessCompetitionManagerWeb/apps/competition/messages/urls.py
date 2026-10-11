from django.urls import path

from apps.competition.messages import views

urlpatterns = [
    path('competitions/<int:cid>/messages', views.MessageListView.as_view()),
    path('competitions/<int:cid>/messages/<int:pk>/read', views.MessageReadView.as_view()),
    path('me/messages', views.MyMessagesView.as_view()),
]
