"""统一缓存封装：命名空间 + 版本号失效。

设计要点（兼容 Redis 与 LocMem）：
- **不用 delete_pattern / SCAN**（LocMem 不支持、Redis 上也会阻塞）：每个命名空间有一个
  版本号，key 里带版本；失效 = 版本 +1，旧 key 自然过期；
- 版本号本身用 ``cache.add`` 初始化（并发安全）；
- ``remember`` 的 producer 只在未命中时执行，返回值必须可序列化（Redis 用 pickle）。
"""

import logging

from django.core.cache import cache

logger = logging.getLogger('gipfel.cache')

VERSION_TIMEOUT = 60 * 60 * 24 * 365


def _version(namespace: str) -> int:
    key = f'cachever:{namespace}'
    try:
        value = cache.get(key)
        if value is None:
            cache.add(key, 1, VERSION_TIMEOUT)
            value = cache.get(key, 1)
        return int(value)
    except Exception:  # noqa: BLE001 —— 缓存不可用：退回版本 0（等价于每次都未命中）
        logger.warning('缓存版本读取失败 namespace=%s', namespace, exc_info=True)
        return 0


def make_key(namespace: str, *parts) -> str:
    suffix = ':'.join(str(part) for part in parts)
    return f'{namespace}:v{_version(namespace)}:{suffix}'


def remember(namespace: str, parts, producer, timeout=None):
    """读缓存；未命中执行 ``producer()`` 并回填。"""
    key = make_key(namespace, *parts)
    try:
        value = cache.get(key)
    except Exception:  # noqa: BLE001 —— Redis 挂了也要能出结果
        logger.warning('缓存读取失败 namespace=%s', namespace, exc_info=True)
        return producer()
    if value is not None:
        return value
    value = producer()
    try:
        cache.set(key, value, timeout)
    except Exception:  # noqa: BLE001 —— 缓存不可用不影响业务
        logger.warning('缓存写入失败 namespace=%s', namespace, exc_info=True)
    return value


def bump(*namespaces: str) -> None:
    """让这些命名空间的缓存全部失效（版本 +1）。"""
    for namespace in namespaces:
        key = f'cachever:{namespace}'
        try:
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 2, VERSION_TIMEOUT)
        except Exception:  # noqa: BLE001
            logger.warning('缓存版本递增失败 namespace=%s', namespace, exc_info=True)


# 资源变更 → 需要失效的缓存命名空间（只放“读多写少”的目录型数据）
RESOURCE_NAMESPACES = {
    'packages': ('contract-types', 'industry-fields'),
    'plugins': ('contract-types',),
    'industry-fields': ('industry-fields',),
    'basedata': ('basedata',),
    'files': ('basedata',),
    'contracts': (),          # 合同本身不缓存列表（要实时）
    'companies': ('company-list',),
    'teams': ('company-list',),
}


def bump_for_resource(resource: str) -> None:
    namespaces = RESOURCE_NAMESPACES.get(resource or '')
    if namespaces:
        bump(*namespaces)
