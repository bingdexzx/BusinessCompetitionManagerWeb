from django.urls import path

from apps.competition.basedata import views

urlpatterns = [
    path('competitions/<int:cid>/basedata/<str:table>', views.BasedataTableView.as_view()),
    path('competitions/<int:cid>/basedata/<str:table>/<int:pk>', views.BasedataRowView.as_view()),
]
