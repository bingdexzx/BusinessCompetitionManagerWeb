"""用户管理路由。

注意：这里全部写成**相对路径**（'users' / 'users/<int:pk>' / 'users/<int:pk>/password'），
由根路由以 path('api/', include('apps.global_.useradmin.urls')) 引入，统一挂到 /api 前缀下：
  GET    /api/users                    账号列表（?page&pageSize&q）
  POST   /api/users                    新建账号
  GET    /api/users/<int:pk>           账号详情
  PATCH  /api/users/<int:pk>           修改账号
  DELETE /api/users/<int:pk>           删除账号
  POST   /api/users/<int:pk>/password  重置密码（顶号）
"""

from django.urls import path

from apps.global_.useradmin import views

urlpatterns = [
    path('users', views.UserListCreateView.as_view()),
    path('users/<int:pk>', views.UserDetailView.as_view()),
    path('users/<int:pk>/password', views.UserPasswordResetView.as_view()),
]
