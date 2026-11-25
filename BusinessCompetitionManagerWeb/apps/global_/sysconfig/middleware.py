"""API 请求限流中间件（系统设置 — 流量限制）。

**必须注册在 ``AuthenticationMiddleware`` 之后**（依赖 ``request.user`` 判角色），建议放在
``CompetitionContextMiddleware`` 之后（此时 ``request.competition_id`` 已解析）。

只拦 ``/api/``，按角色每分钟窗口计数（计数落库，多进程 worker 共享），超限 429 + ``Retry-After``
（到窗口结束秒数）；``api.enabled=false`` 放行；配置读取带 5 秒缓存。角色：superuser /
compSuperAdmin / player / anonymous（比赛身份取 ``request.competition_id`` 或头）。"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from apps.common import context as ctx
from apps.common.authority import user_membership
from apps.common.devices import client_ip
from apps.global_.sysconfig.models import RequestThrottle
from apps.global_.sysconfig.service import get_effective_config

logger = logging.getLogger(__name__)

API_PREFIX = '/api/'

WINDOW_SECONDS = 60

ROLE_BY_IDENTITY = {
    'ADMIN': 'admin',
    'PLAYER': 'player',
}

# 过期计数行清理：每 CLEANUP_INTERVAL 秒最多一次，删 CLEANUP_AFTER_SECONDS 之前的旧行
CLEANUP_INTERVAL_SECONDS = 60
CLEANUP_AFTER_SECONDS = 600

_cleanup_lock = threading.Lock()
_last_cleanup_at = 0.0


def resolve_role(request) -> str:
    """请求 → 限额角色（superuser / compSuperAdmin / player / anonymous）。"""
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return 'anonymous'
    if getattr(user, 'is_superuser', False):
        return 'superuser'
    competition_id = (
        getattr(request, 'competition_id', None)
        or request.META.get('HTTP_X_COMPETITION_ID')
        or ctx.get_competition_id()
    )
    try:
        competition_id = int(competition_id) if competition_id else None
    except (TypeError, ValueError):
        competition_id = None
    if competition_id:
        try:
            membership = user_membership(user, competition_id)
        except Exception:  # noqa: BLE001 —— 查不到比赛身份按无身份处理
            membership = None
        if membership is not None:
            role = ROLE_BY_IDENTITY.get(membership.identity)
            if role:
                return role
    return 'anonymous'


def throttle_identity(request) -> str:
    """计数主体：登录用户用 userId，匿名用客户端 IP。"""
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_authenticated', False) and getattr(user, 'pk', None):
        return str(user.pk)
    return client_ip(request) or '-'


class RateLimitMiddleware(MiddlewareMixin):
    """API 每分钟限流（注册位置见模块文档：AuthenticationMiddleware 之后）。"""

    def process_request(self, request):
        if not request.path.startswith(API_PREFIX):
            return None
        try:
            return self._throttle(request)
        except Exception:  # noqa: BLE001 —— 限流自身故障时放行，绝不挡住业务
            logger.exception('RateLimitMiddleware 内部错误，本次请求放行')
            return None

    def _throttle(self, request):
        config = get_effective_config()
        api_cfg = config.get('api') or {}
        if not api_cfg.get('enabled', True):
            return None
        role = resolve_role(request)
        limit = (api_cfg.get('perMinute') or {}).get(role)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            return None
        self._maybe_cleanup()

        retry_after = _hit(throttle_identity(request), role, limit)
        if retry_after is None:
            return None
        return JsonResponse(
            {'code': 429, 'message': '请求过于频繁，请稍后再试', 'details': ''},
            status=429, headers={'Retry-After': str(retry_after)})

    def _maybe_cleanup(self):
        """每分钟最多一次：删除窗口过期且未锁定的计数行。"""
        global _last_cleanup_at
        now = time.monotonic()
        with _cleanup_lock:
            if now - _last_cleanup_at < CLEANUP_INTERVAL_SECONDS:
                return
            _last_cleanup_at = now
        try:
            RequestThrottle.objects.filter(
                window_start__lt=timezone.now() - timedelta(seconds=CLEANUP_AFTER_SECONDS),
            ).filter(
                Q(locked_until__isnull=True) | Q(locked_until__lte=timezone.now()),
            ).delete()
        except Exception:  # noqa: BLE001 —— 清理失败不影响请求
            logger.exception('清理过期限流计数行失败')


def _hit(subject: str, role: str, limit: int):
    """计一次请求；返回 None（放行）或 Retry-After 秒数（429，窗口内超 limit 则锁到窗口结束）。"""
    now = timezone.now()
    key = f'api:{subject}:{role}'[:220]

    with transaction.atomic():
        row, created = RequestThrottle.objects.get_or_create(
            key=key, defaults={'window_start': now, 'count': 1})
        if created:
            return None
        row = RequestThrottle.objects.select_for_update().get(key=key)
        if row.locked_until is not None and row.locked_until > now:
            return max(1, math.ceil((row.locked_until - now).total_seconds()))
        if row.window_start is None or now - row.window_start >= timedelta(seconds=WINDOW_SECONDS):
            row.window_start = now
            row.count = 1
            row.locked_until = None
            row.save(update_fields=['window_start', 'count', 'locked_until', 'updated_at'])
            return None
        row.count += 1
        if row.count > limit:
            row.locked_until = row.window_start + timedelta(seconds=WINDOW_SECONDS)
            row.save(update_fields=['count', 'locked_until', 'updated_at'])
            return max(1, math.ceil((row.locked_until - now).total_seconds()))
        row.save(update_fields=['count', 'updated_at'])
        return None
