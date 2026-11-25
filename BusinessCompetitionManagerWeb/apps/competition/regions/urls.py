"""区域域路由：由 backend 根路由以 path("api/", include("apps.competition.regions.urls")) 引入。"""

from django.urls import path

from apps.competition.regions import views

urlpatterns = [
    path('competitions/<int:cid>/regions', views.RegionListView.as_view()),
    # 区域总览（旧系统口径）：地图概览聚合 + 按区域名保存卡片。
    # 注意顺序：map-overview / by-name 必须在 <int:pk> 之前。
    path('competitions/<int:cid>/regions/map-overview', views.RegionMapOverviewView.as_view()),
    path('competitions/<int:cid>/regions/by-name/<path:name>/overview-cards',
         views.RegionCardsByNameView.as_view()),
    path('competitions/<int:cid>/regions/<int:pk>', views.RegionDetailView.as_view()),
    path('competitions/<int:cid>/regions/<int:pk>/overview-cards',
         views.RegionOverviewCardsView.as_view()),
    # 区域字段：定义由比赛包提供；值按区域读 / 超级管理员手工改
    path('competitions/<int:cid>/region-fields',
         views.RegionFieldDefinitionListView.as_view()),
    path('competitions/<int:cid>/regions/by-name/<path:name>/field-values',
         views.RegionFieldValuesByNameView.as_view()),
    path('competitions/<int:cid>/regions/by-name/<path:name>/field-values/<str:key>',
         views.RegionFieldValueByNameView.as_view()),
    path('competitions/<int:cid>/consumer-demands', views.ConsumerDemandListView.as_view()),
    path('competitions/<int:cid>/consumer-demands/<int:pk>', views.ConsumerDemandDetailView.as_view()),
]
