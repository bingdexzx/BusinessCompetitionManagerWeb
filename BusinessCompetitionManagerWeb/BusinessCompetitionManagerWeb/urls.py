"""根路由（§12 API 设计概览）。"""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({'status': 'ok', 'service': 'gipfel'})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health', health),
    # 全局域
    path('api/', include('apps.global_.accounts.urls')),
    path('api/', include('apps.global_.useradmin.urls')),  # 用户管理（仅系统超管）
    path('api/', include('apps.global_.schools.urls')),
    path('api/', include('apps.global_.competitions.urls')),
    path('api/', include('apps.global_.jobs.urls')),
    path('api/', include('apps.global_.memberships.urls')),
    path('api/', include('apps.global_.logs.urls')),
    path('api/', include('apps.global_.packages.urls')),
    path('api/', include('apps.global_.teams.urls')),
    path('api/', include('apps.global_.invites.urls')),
    path('api/', include('apps.global_.profiles.urls')),
    # 系统级站内信（独立于比赛）
    path('api/', include('apps.global_.messages.urls')),
    # 系统设置（流量限制配置）
    path('api/', include('apps.global_.sysconfig.urls')),
    # 文件上传服务（通用上传 / 地图背景 / 消息图片）
    path('api/', include('apps.global_.files.urls')),
    # 比赛域（/api/competitions/{cid}/... 由多库路由解析到对应比赛库）
    path('api/', include('apps.competition.companies.urls')),
    # 产业字段元数据（字段键 → 中文名，前端展示用）
    path('api/', include('apps.competition.industries.urls')),
    path('api/', include('apps.competition.contracts.urls')),
    path('api/', include('apps.competition.fiscal.urls')),
    path('api/', include('apps.competition.fieldlogs.urls')),
    path('api/', include('apps.competition.audit.urls')),
    path('api/', include('apps.competition.settlement.urls')),
    # 数据管理（10 类基础数据维护；不再随比赛包导入）
    path('api/', include('apps.competition.basedata.urls')),
    # 股票模块（契约：股票模块与同步优化.md §4 /api/competitions/{cid}/stock/...）
    path('api/', include('apps.competition.stock.urls')),
    # 区域与消费者需求（2026-10 决策补齐；区域总览卡片）
    path('api/', include('apps.competition.regions.urls')),
    # 工具箱（计时器）
    path('api/', include('apps.competition.tools.urls')),
]
