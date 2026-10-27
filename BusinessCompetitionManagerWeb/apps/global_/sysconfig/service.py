"""流量限制配置的服务层：默认配置 / 严格校验 / 5 秒读缓存。

配置读取带 **5 秒缓存**（中间件与登录限流每请求都要读，避免每请求查库），PUT/reset 后立即
失效。PUT 严格校验：只允许 login/api 两段且字段不多不少；数值必须**正整数**（bool / float /
数字字符串一律拒绝）；``api.perMinute`` 固定五角色键。"""

from __future__ import annotations

import copy
import threading
import time

ROLE_KEYS = ('superuser', 'compSuperAdmin', 'admin', 'player', 'anonymous')

LOGIN_KEYS = ('failLimit', 'windowSeconds', 'lockSeconds')

DEFAULT_RATE_LIMIT_CONFIG = {
    'login': {'failLimit': 10, 'windowSeconds': 300, 'lockSeconds': 900},
    'api': {
        'enabled': True,
        'perMinute': {
            'superuser': 600,
            'compSuperAdmin': 300,
            'admin': 200,
            'player': 120,
            # 匿名按**客户端 IP** 计数：同机多标签页 / 同一 NAT 出口共享额度，
            # 30 太低会误伤正常浏览（实测多标签页 + 学校搜索即 429），取 120（2 req/s）。
            'anonymous': 120,
        },
    },
}

CONFIG_CACHE_TTL_SECONDS = 5.0

_cache_lock = threading.Lock()
_UNSET = object()  # 缓存未加载哨兵
_cache_state = {'loaded_at': 0.0, 'value': _UNSET}


def invalidate_config_cache() -> None:
    """失效配置缓存（配置保存 / 重置后调用，测试也用它保证隔离）。"""
    with _cache_lock:
        _cache_state['loaded_at'] = 0.0
        _cache_state['value'] = _UNSET


def load_saved_config():
    """读取库中保存的配置（5 秒缓存）；返回 dict 或 None（未保存/读取失败，调用方回退）。"""
    now = time.monotonic()
    with _cache_lock:
        if _cache_state['value'] is not _UNSET and now - _cache_state['loaded_at'] < CONFIG_CACHE_TTL_SECONDS:
            value = _cache_state['value']
            return copy.deepcopy(value) if value is not None else None
    try:
        from apps.global_.sysconfig.models import RateLimitConfig

        value = RateLimitConfig.load()
    except Exception:  # noqa: BLE001 —— 读取失败按「取不到配置」处理，不缓存
        return None
    if not isinstance(value, dict):
        value = None
    with _cache_lock:
        _cache_state['loaded_at'] = now
        _cache_state['value'] = value
    return copy.deepcopy(value) if value is not None else None


def get_effective_config() -> dict:
    """当前生效配置：已保存用保存值，否则用默认配置（深拷贝，调用方可安全修改）。"""
    saved = load_saved_config()
    if isinstance(saved, dict) and 'login' in saved and 'api' in saved:
        return copy.deepcopy(saved)
    return copy.deepcopy(DEFAULT_RATE_LIMIT_CONFIG)


def load_saved_login_params():
    """登录限流三参数 ``(failLimit, windowSeconds, lockSeconds)``；未保存/非法返回 None，由调用方回退 settings。"""
    saved = load_saved_config()
    login = saved.get('login') if isinstance(saved, dict) else None
    if not isinstance(login, dict):
        return None
    values = []
    for key in LOGIN_KEYS:
        value = login.get(key)
        if not _is_positive_int(value):
            return None
        values.append(int(value))
    return tuple(values)


def save_config(config: dict) -> dict:
    from apps.global_.sysconfig.models import RateLimitConfig

    saved = RateLimitConfig.save_config(config)
    invalidate_config_cache()
    return saved


def reset_config() -> dict:
    return save_config(copy.deepcopy(DEFAULT_RATE_LIMIT_CONFIG))


def _is_positive_int(value) -> bool:
    """正整数（拒绝 bool / float / str）。"""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_config(payload):
    """严格校验 PUT 的 config 整体：返回 ``(config, None)`` 或 ``(None, 中文错误)``。"""
    if not isinstance(payload, dict):
        return None, '配置必须是 JSON 对象'
    if set(payload.keys()) != {'login', 'api'}:
        return None, '配置只允许 login / api 两个配置段'

    login = payload.get('login')
    if not isinstance(login, dict):
        return None, 'login 配置段必须是 JSON 对象'
    if set(login.keys()) != set(LOGIN_KEYS):
        return None, 'login 配置段只允许 failLimit / windowSeconds / lockSeconds'
    for key in LOGIN_KEYS:
        if not _is_positive_int(login.get(key)):
            return None, f'login.{key} 必须是正整数'

    api = payload.get('api')
    if not isinstance(api, dict):
        return None, 'api 配置段必须是 JSON 对象'
    if set(api.keys()) != {'enabled', 'perMinute'}:
        return None, 'api 配置段只允许 enabled / perMinute'
    if not isinstance(api.get('enabled'), bool):
        return None, 'api.enabled 必须是布尔值'
    per_minute = api.get('perMinute')
    if not isinstance(per_minute, dict):
        return None, 'api.perMinute 必须是 JSON 对象'
    if set(per_minute.keys()) != set(ROLE_KEYS):
        return None, 'api.perMinute 键集合必须为 superuser / compSuperAdmin / admin / player / anonymous'
    for role in ROLE_KEYS:
        if not _is_positive_int(per_minute.get(role)):
            return None, f'api.perMinute.{role} 必须是正整数'

    config = {
        'login': {key: int(login[key]) for key in LOGIN_KEYS},
        'api': {
            'enabled': api['enabled'],
            'perMinute': {role: int(per_minute[role]) for role in ROLE_KEYS},
        },
    }
    return config, None
