from django.urls import path

from apps.global_.teams import views

urlpatterns = [
    path('competitions/<int:cid>/teams', views.TeamListCreateView.as_view()),
    path('competitions/<int:cid>/teams/join', views.TeamJoinView.as_view()),
    path('competitions/<int:cid>/teams/<int:tid>', views.TeamDetailView.as_view()),
    path('competitions/<int:cid>/teams/<int:tid>/join-codes', views.TeamJoinCodeView.as_view()),
    path('competitions/<int:cid>/teams/<int:tid>/industry', views.TeamIndustryAdjustView.as_view()),
    # 分配/修改队伍公司（选产业 + 填公司名称；系统超级管理员 / 比赛超级管理员）
    path('competitions/<int:cid>/teams/<int:tid>/company',
         views.TeamCompanyAssignView.as_view()),
]
