"""基础数据管理路由（统一通用契约，见 views 模块 docstring）。"""

from django.urls import path

from apps.competition.basedata import views

urlpatterns = [
    path('competitions/<int:cid>/basedata/<str:table>', views.BasedataTableView.as_view()),
    path('competitions/<int:cid>/basedata/<str:table>/<int:pk>', views.BasedataRowView.as_view()),
    path('competitions/<int:cid>/basedata/<str:table>/<int:pk>/impact',
         views.BasedataImpactView.as_view()),
]
