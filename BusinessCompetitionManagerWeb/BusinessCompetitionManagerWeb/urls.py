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
    path('api/', include('apps.global_.schools.urls')),
    path('api/', include('apps.global_.competitions.urls')),
    path('api/', include('apps.global_.memberships.urls')),
    path('api/', include('apps.global_.logs.urls')),
    path('api/', include('apps.global_.packages.urls')),
    path('api/', include('apps.global_.teams.urls')),
    path('api/', include('apps.global_.invites.urls')),
    path('api/', include('apps.global_.profiles.urls')),
    # 比赛域（/api/competitions/{cid}/... 由多库路由解析到对应比赛库）
    path('api/', include('apps.competition.companies.urls')),
    path('api/', include('apps.competition.contracts.urls')),
    path('api/', include('apps.competition.fiscal.urls')),
    path('api/', include('apps.competition.fieldlogs.urls')),
    path('api/', include('apps.competition.messages.urls')),
    path('api/', include('apps.competition.audit.urls')),
    path('api/', include('apps.competition.settlement.urls')),
]
