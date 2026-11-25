"""股票系统路由（契约 §4）：由根 urls.py 以
``path('api/', include('apps.competition.stock.urls'))`` 挂载（无尾随斜杠）。

路径全量为 /api/competitions/{cid}/stock/...（§4）；
路由顺序：静态子路径（stocks/{code}/candles）置于 stocks/{code} 之前，避免误匹配。
"""

from django.urls import path

from . import views

urlpatterns = [
    # 行情与交易（§4.1）
    path('competitions/<int:cid>/stock/stocks', views.StockListView.as_view()),
    path('competitions/<int:cid>/stock/stocks/<str:code>/candles', views.StockCandlesView.as_view()),
    path('competitions/<int:cid>/stock/stocks/<str:code>', views.StockDetailView.as_view()),
    path('competitions/<int:cid>/stock/book', views.BookView.as_view()),
    # 资金账户管理（超级管理员；新增/编辑/删除，旧系统「新增资金账户」能力）
    path('competitions/<int:cid>/stock/accounts', views.AccountListCreateView.as_view()),
    path('competitions/<int:cid>/stock/accounts/<int:pk>', views.AccountItemView.as_view()),
    path('competitions/<int:cid>/stock/orders', views.OrderListCreateView.as_view()),
    path('competitions/<int:cid>/stock/orders/<int:pk>', views.OrderItemView.as_view()),
    path('competitions/<int:cid>/stock/round/advance', views.AdvanceRoundView.as_view()),
    path('competitions/<int:cid>/stock/market', views.MarketView.as_view()),
    # 同步协议（§4.2，核心性能项）
    path('competitions/<int:cid>/stock/sync', views.SyncView.as_view()),
]
