"""登录失败限流（旧系统等价能力）。

策略（默认，可由 settings 覆盖）：**同一 用户名|IP 在 5 分钟窗口内失败 10 次 → 锁 15 分钟**；
登录成功即清零。计数落库（多进程 worker 共享，进程内计数会被 worker 数摊薄）。

阈值优先读「系统设置 — 流量限制」的 login 段（apps.global_.sysconfig.models.RateLimitConfig，
带 5 秒缓存）；**取不到配置**（从未保存过 / 配置非法 / 读取失败）时回退 settings 默认值
（LOGIN_FAIL_LIMIT / LOGIN_FAIL_WINDOW_SECONDS / LOGIN_LOCK_SECONDS）。
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.devices import client_ip
from apps.global_.accounts.models import LoginThrottle


def login_throttle_params() -> tuple[int, int, int]:
    """登录限流三参数 ``(failLimit, windowSeconds, lockSeconds)``。

    优先读流量限制配置的 login 段（5 秒缓存），取不到配置回退 settings 默认值。
    """
    try:
        from apps.global_.sysconfig.service import load_saved_login_params

        params = load_saved_login_params()
    except Exception:  # noqa: BLE001 —— 配置模块不可用时按「取不到配置」处理
        params = None
    if params is not None:
        return params
    return (
        int(getattr(settings, 'LOGIN_FAIL_LIMIT', 10)),
        int(getattr(settings, 'LOGIN_FAIL_WINDOW_SECONDS', 300)),
        int(getattr(settings, 'LOGIN_LOCK_SECONDS', 900)),
    )


def throttle_key(username: str, request) -> str:
    ip = client_ip(request) or '-'
    return f'{(username or "").lower()}|{ip}'[:220]


def locked_until(key: str):
    """返回锁定截止时间；未锁定返回 None。"""
    row = LoginThrottle.objects.filter(key=key).first()
    if row is None or row.locked_until is None:
        return None
    if row.locked_until <= timezone.now():
        # 锁已过期：顺手解锁，窗口重新计数
        row.locked_until = None
        row.fail_count = 0
        row.window_start = timezone.now()
        row.save(update_fields=['locked_until', 'fail_count', 'window_start'])
        return None
    return row.locked_until


def record_failure(key: str) -> None:
    """记一次失败；窗口内达到上限则锁定。

    原子性：整段在事务 + ``SELECT ... FOR UPDATE`` 行锁内完成。多进程/多 worker
    并发登录失败时，计数与窗口判定都基于行锁保护的**已提交值**，不会像旧的
    ``F() + refresh_from_db`` 那样读到过期计数而漏锁（严格「窗口内 N 次 → 锁定」）。
    """
    limit, window, lock_seconds = login_throttle_params()
    now = timezone.now()

    with transaction.atomic():
        row, created = LoginThrottle.objects.get_or_create(
            key=key, defaults={'window_start': now, 'fail_count': 1})
        if created:
            return  # 窗口首条失败：计数 1，未达上限
        # 先拿行锁再读，保证并发下 window_start / fail_count 是已提交的稳定值
        row = LoginThrottle.objects.select_for_update().get(key=key)
        if row.window_start is None or now - row.window_start > timedelta(seconds=window):
            row.window_start = now
            row.fail_count = 0
        row.fail_count += 1
        if row.fail_count >= limit:
            row.locked_until = now + timedelta(seconds=lock_seconds)
            row.save(update_fields=['fail_count', 'window_start', 'locked_until', 'updated_at'])
        else:
            row.save(update_fields=['fail_count', 'window_start', 'updated_at'])


def record_success(key: str) -> None:
    """登录成功：清零并解锁。"""
    LoginThrottle.objects.filter(key=key).delete()
