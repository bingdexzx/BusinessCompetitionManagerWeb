"""基础数据管理路由（统一通用契约，见 views 模块 docstring）。"""

from django.urls import path

from apps.competition.basedata import views

urlpatterns = [
    # 地图配置/导入（具体路径必须先于通用 <str:table>，否则会被当成表名）
    path('competitions/<int:cid>/basedata/map-settings', views.MapSettingsView.as_view()),
    path('competitions/<int:cid>/basedata/map-import', views.MapImportView.as_view()),
    path('competitions/<int:cid>/basedata/<str:table>', views.BasedataTableView.as_view()),
    path('competitions/<int:cid>/basedata/<str:table>/<int:pk>', views.BasedataRowView.as_view()),
    path('competitions/<int:cid>/basedata/<str:table>/<int:pk>/impact',
         views.BasedataImpactView.as_view()),
]
