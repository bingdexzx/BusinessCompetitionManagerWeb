"""文件上传服务路由（相对 /api 前缀）。

由根路由以 path('api/', include('apps.global_.files.urls')) 引入。
"""

from django.urls import path

from apps.global_.files.views import (
    FileUploadView,
    MapBackgroundView,
    MessageImageUploadView,
    ServeFileView,
)

urlpatterns = [
    # 通用上传 / 读取
    path('files/upload', FileUploadView.as_view()),
    path('files/view/<path:name>', ServeFileView.as_view()),
    # 比赛地图背景
    path('competitions/<int:cid>/files/map-background', MapBackgroundView.as_view()),
    # 站内信图片
    path('messages/upload-image', MessageImageUploadView.as_view()),
]
