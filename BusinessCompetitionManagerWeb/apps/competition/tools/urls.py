"""工具箱路由：由根路由以 path("api/", include("apps.competition.tools.urls")) 引入。"""

from django.urls import path

from apps.competition.tools import views

urlpatterns = [
    path('competitions/<int:cid>/timers', views.CompetitionTimerListView.as_view()),
    path('competitions/<int:cid>/timers/<int:pk>', views.CompetitionTimerDetailView.as_view()),
]
