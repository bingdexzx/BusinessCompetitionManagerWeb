from django.urls import path

from apps.global_.competitions import permissions_view, views

urlpatterns = [
    path('competitions', views.CompetitionListCreateView.as_view()),
    path('competitions/<int:cid>', views.CompetitionDetailView.as_view()),
    path('competitions/<int:cid>/meta', views.CompetitionMetaView.as_view()),
    path('competitions/<int:cid>/transition', views.CompetitionTransitionView.as_view()),
    # 仪表盘布局（比赛包 dashboard.json；组件绑定产业字段值）
    path('competitions/<int:cid>/dashboard', views.DashboardLayoutView.as_view()),
    path('competitions/<int:cid>/permissions',
         permissions_view.CompetitionPermissionView.as_view()),
]
