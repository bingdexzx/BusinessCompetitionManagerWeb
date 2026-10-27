from django.urls import path

from apps.competition.settlement import views

urlpatterns = [
    path('competitions/<int:cid>/settlement/config', views.ScoringConfigView.as_view()),
    path('competitions/<int:cid>/settlement/config/<str:kind>/<int:pk>',
         views.ScoringConfigDeleteView.as_view()),
    path('competitions/<int:cid>/settlement/candidates', views.AwardCandidateView.as_view()),
    path('competitions/<int:cid>/settlement/run', views.SettlementRunView.as_view()),
    path('competitions/<int:cid>/settlement/result', views.SettlementResultView.as_view()),
    # 结算名次（只读）
    path('competitions/<int:cid>/awards', views.AwardListView.as_view()),
    # 奖项发放（人工）
    path('competitions/<int:cid>/awards/grants', views.AwardGrantView.as_view()),
    path('competitions/<int:cid>/awards/grants/<int:pk>', views.AwardGrantDetailView.as_view()),
]
