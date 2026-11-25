"""产业域路由（比赛域）：由根路由以 path("api/", include(...)) 引入。"""

from django.urls import path

from apps.competition.industries import views

urlpatterns = [
    path('competitions/<int:cid>/industry-fields', views.IndustryFieldListView.as_view()),
    path('competitions/<int:cid>/industry-fields/reorder',
         views.IndustryFieldReorderView.as_view()),
    path('competitions/<int:cid>/industry-fields/<str:key>',
         views.IndustryFieldGroupView.as_view()),
]
