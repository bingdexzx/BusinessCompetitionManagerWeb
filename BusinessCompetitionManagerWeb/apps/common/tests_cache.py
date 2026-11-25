"""缓存封装测试：版本失效、producer 只执行一次、缓存异常不影响业务。"""

from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from apps.common import cache as cache_util


class NamespaceCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_remember_calls_producer_once(self):
        calls = []
        first = cache_util.remember('probe-ns', (1, 'a'), lambda: calls.append(1) or {'x': 1})
        second = cache_util.remember('probe-ns', (1, 'a'), lambda: calls.append(1) or {'x': 2})
        self.assertEqual(first, {'x': 1})
        self.assertEqual(second, {'x': 1})   # 第二次命中缓存
        self.assertEqual(len(calls), 1)

    def test_bump_invalidates_namespace(self):
        cache_util.remember('probe-ns', ('k',), lambda: 'old')
        cache_util.bump('probe-ns')
        self.assertEqual(
            cache_util.remember('probe-ns', ('k',), lambda: 'new'), 'new')

    def test_bump_for_resource_maps_packages(self):
        cache_util.remember('contract-types', ('k',), lambda: 'old')
        cache_util.bump_for_resource('packages')
        self.assertEqual(
            cache_util.remember('contract-types', ('k',), lambda: 'new'), 'new')

    def test_unknown_resource_does_not_fail(self):
        cache_util.bump_for_resource('nothing-here')   # 不抛异常

    def test_cache_failure_is_graceful(self):
        with mock.patch.object(cache, 'get', side_effect=RuntimeError('redis down')):
            with mock.patch.object(cache, 'set', side_effect=RuntimeError('redis down')):
                # get 失败会把异常抛给调用方（上游按不可用处理），这里只验证 set 失败不影响返回值
                value = cache_util.remember('probe-ns', ('k',), lambda: 'value')
        self.assertEqual(value, 'value')
