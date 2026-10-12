from django.urls import path

from apps.global_.messages import views

urlpatterns = [
    path('messages', views.InboxView.as_view()),
    path('messages/sent', views.SentView.as_view()),
    path('messages/send', views.SendView.as_view()),
    path('messages/address-book', views.AddressBookView.as_view()),
    path('messages/read-all', views.ReadAllView.as_view()),
    path('messages/<int:pk>/read', views.ReadView.as_view()),
]
