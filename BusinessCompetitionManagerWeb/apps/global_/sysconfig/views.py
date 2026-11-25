"""系统设置 — 流量限制配置 API（仅超级管理员）。

路由：GET/PUT ``/api/system/rate-limit``、POST ``.../reset``、DELETE ``.../records``；错误响应
统一 {code, message, details}（风格见 apps.common.errors）。"""

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSystemSuperAdmin
from apps.global_.accounts.models import LoginThrottle
from apps.global_.sysconfig.models import RequestThrottle
from apps.global_.sysconfig.service import (
    get_effective_config, invalidate_config_cache, reset_config, save_config,
    validate_config,
)


def _error(message, code=400, details=''):
    return Response({'code': code, 'message': message, 'details': details}, status=code)


class RateLimitConfigView(APIView):
    """GET：读取当前配置 + 限流统计；PUT：整体保存配置（严格校验）。"""

    permission_classes = [IsSystemSuperAdmin]

    def get(self, request):
        now = timezone.now()
        stats = {
            # 计数记录数（API 每分钟计数 + 登录失败计数）
            'throttleRecords': (
                RequestThrottle.objects.count() + LoginThrottle.objects.count()
            ),
            'activeLocks': (
                RequestThrottle.objects.filter(locked_until__gt=now).count()
                + LoginThrottle.objects.filter(locked_until__gt=now).count()
            ),
        }
        return Response({'config': get_effective_config(), 'stats': stats})

    def put(self, request):
        config, error = validate_config(request.data)
        if error:
            return _error(error)
        return Response(save_config(config))


class RateLimitResetView(APIView):
    """POST：恢复默认配置。"""

    permission_classes = [IsSystemSuperAdmin]

    def post(self, request):
        return Response(reset_config())


class RateLimitRecordsView(APIView):
    """DELETE：清空全部限流记录（API 计数 + 登录失败限流一并清空）。"""

    permission_classes = [IsSystemSuperAdmin]

    def delete(self, request):
        cleared = RequestThrottle.objects.all().delete()[0]
        cleared += LoginThrottle.objects.all().delete()[0]
        invalidate_config_cache()
        return Response({'ok': True, 'cleared': cleared})
