"""系统设置 — 流量限制配置测试（apps.global_.sysconfig）。

- 不依赖根路由挂载：本模块自带 urlpatterns 模拟
  ``path('api/', include('apps.global_.sysconfig.urls'))``（登录限流用例另挂
  accounts 登录路由），用 ``override_settings(ROOT_URLCONF=__name__)`` 生效；
- 中间件用例直接实例化 ``RateLimitMiddleware`` 调用 process_request，
  不依赖 MIDDLEWARE 注册；
- 鉴权用 ``rest_framework.test.APIClient.force_authenticate``，不走真实 JWT；
- settings 里真实注册的 RateLimitMiddleware 会计数每个 /api/ 请求，故
  **计数/清空类断言前先保存 api.enabled=false 的配置**（配置带 5 秒缓存，
  保存后立即失效），让断言精确到本用例自建的记录。
"""

import copy
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import include, path
from django.utils import timezone
from rest_framework.test import APIClient

from apps.global_.accounts.models import LoginThrottle
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from apps.global_.sysconfig import middleware as middleware_module
from apps.global_.sysconfig.middleware import RateLimitMiddleware, resolve_role
from apps.global_.sysconfig.models import RateLimitConfig, RequestThrottle
from apps.global_.sysconfig.service import (
    DEFAULT_RATE_LIMIT_CONFIG,
    invalidate_config_cache,
    save_config,
)

User = get_user_model()

# 模拟根路由挂载（生产中由根路由以 path('api/', include('apps.global_.sysconfig.urls')) 引入）
urlpatterns = [
    path('api/', include('apps.global_.sysconfig.urls')),
    path('api/', include('apps.global_.accounts.urls')),  # /api/auth/login（登录限流用例）
]

LIST_URL = '/api/system/rate-limit'
RESET_URL = '/api/system/rate-limit/reset'
RECORDS_URL = '/api/system/rate-limit/records'


def build_config(login=None, per_minute=None, enabled=True):
    """基于默认配置构造测试配置。"""
    config = copy.deepcopy(DEFAULT_RATE_LIMIT_CONFIG)
    if login:
        config['login'].update(login)
    if per_minute:
        config['api']['perMinute'].update(per_minute)
    config['api']['enabled'] = enabled
    return config


def disable_api_counting():
    """保存 api.enabled=false 并失效缓存：真实中间件不再计数，计数断言才精确。"""
    save_config(build_config(enabled=False))


class ConfigIsolationMixin:
    """每个用例后清掉配置行并失效 5 秒缓存，避免用例间串配置。"""

    def tearDown(self):
        RateLimitConfig.objects.all().delete()
        invalidate_config_cache()
        super().tearDown()


# ---------------------------------------------------------------- 配置 API


@override_settings(ROOT_URLCONF=__name__)
class RateLimitConfigApiTests(ConfigIsolationMixin, TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'adminpass123')
        self.member = User.objects.create_user('member', 'member@example.com', 'memberpass123')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_get_default_config(self):
        """从未保存过配置：返回默认配置 + 统计。"""
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body.keys()), {'config', 'stats'})
        self.assertEqual(body['config'], DEFAULT_RATE_LIMIT_CONFIG)
        self.assertEqual(set(body['stats'].keys()), {'throttleRecords', 'activeLocks'})
        self.assertIsInstance(body['stats']['throttleRecords'], int)
        self.assertEqual(body['stats']['activeLocks'], 0)

    def test_put_saves_config(self):
        """PUT body 为 config 整体：严格校验通过 → 落库并返回保存后的 config。"""
        payload = build_config(
            login={'failLimit': 5, 'windowSeconds': 60, 'lockSeconds': 120},
            per_minute={'anonymous': 10, 'player': 60},
            enabled=False,
        )
        resp = self.client.put(LIST_URL, payload, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), payload)

        # 落库（单例 id=1）
        self.assertEqual(RateLimitConfig.objects.count(), 1)
        self.assertEqual(RateLimitConfig.objects.get(pk=1).config, payload)

        # GET 返回保存后的配置
        invalidate_config_cache()
        self.assertEqual(self.client.get(LIST_URL).json()['config'], payload)

    def test_put_rejects_invalid_fields(self):
        """非法字段一律 400 {code, message 中文, details}。"""
        valid_login = {'failLimit': 10, 'windowSeconds': 300, 'lockSeconds': 900}
        valid_per_minute = copy.deepcopy(DEFAULT_RATE_LIMIT_CONFIG['api']['perMinute'])
        cases = {
            '整体不是对象': [1, 2],
            '顶层多余字段': {**build_config(), 'extra': 1},
            '顶层缺 api': {'login': valid_login},
            'failLimit 为 0': build_config(login={'failLimit': 0}),
            'failLimit 为负': build_config(login={'failLimit': -3}),
            'failLimit 为布尔': build_config(login={'failLimit': True}),
            'failLimit 为浮点': build_config(login={'failLimit': 1.5}),
            'failLimit 为字符串': build_config(login={'failLimit': '10'}),
            'login 缺字段': {'login': {'failLimit': 10}, 'api': build_config()['api']},
            'login 多余字段': build_config(login={'extra': 1}),
            'enabled 非布尔': build_config(enabled=1),
            'perMinute 缺角色': {
                'login': valid_login,
                'api': {'enabled': True, 'perMinute': {k: v for k, v in valid_per_minute.items() if k != 'anonymous'}},
            },
            'perMinute 多余角色': {
                'login': valid_login,
                'api': {'enabled': True, 'perMinute': {**valid_per_minute, 'guest': 1}},
            },
            'perMinute 值非正整数': build_config(per_minute={'player': 0}),
        }
        for label, payload in cases.items():
            with self.subTest(label):
                resp = self.client.put(LIST_URL, payload, format='json')
                self.assertEqual(resp.status_code, 400)
                body = resp.json()
                self.assertEqual(body['code'], 400)
                self.assertTrue(body['message'])  # 中文错误提示
                self.assertEqual(body['details'], '')
        # 非法配置一律不落库
        self.assertFalse(RateLimitConfig.objects.exists())

    def test_reset_restores_default(self):
        """改过配置后 reset → 恢复默认配置。"""
        self.client.put(LIST_URL, build_config(login={'failLimit': 3}), format='json')
        resp = self.client.post(RESET_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), DEFAULT_RATE_LIMIT_CONFIG)
        invalidate_config_cache()
        self.assertEqual(self.client.get(LIST_URL).json()['config'], DEFAULT_RATE_LIMIT_CONFIG)

    def test_delete_records_clears_api_and_login_throttles(self):
        """清空记录：RequestThrottle 与 LoginThrottle 一并清空，cleared 为总行数。"""
        disable_api_counting()  # 真实中间件不计数，断言精确
        now = timezone.now()
        RequestThrottle.objects.create(key='api:1:player', window_start=now, count=2)
        RequestThrottle.objects.create(
            key='api:2:admin', window_start=now, count=5,
            locked_until=now + timedelta(seconds=60))
        LoginThrottle.objects.create(key='bob|127.0.0.1', fail_count=3)

        resp = self.client.delete(RECORDS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'ok': True, 'cleared': 3})
        self.assertEqual(RequestThrottle.objects.count(), 0)
        self.assertEqual(LoginThrottle.objects.count(), 0)

    def test_stats_counts_records_and_locks(self):
        """统计：计数记录数（API + 登录）与生效锁数。"""
        disable_api_counting()
        now = timezone.now()
        RequestThrottle.objects.create(key='api:1:player', window_start=now, count=1)
        RequestThrottle.objects.create(
            key='api:2:admin', window_start=now, count=9,
            locked_until=now + timedelta(seconds=30))  # 生效锁
        LoginThrottle.objects.create(
            key='bob|127.0.0.1', fail_count=2, locked_until=now - timedelta(seconds=5))  # 过期锁不算

        stats = self.client.get(LIST_URL).json()['stats']
        self.assertEqual(stats['throttleRecords'], 3)
        self.assertEqual(stats['activeLocks'], 1)

    def test_non_superuser_forbidden(self):
        """非系统超级管理员 → 403 {code: 403, message 中文}（四个端点全部拦截）。"""
        client = APIClient()
        client.force_authenticate(self.member)
        calls = [
            ('GET', lambda: client.get(LIST_URL)),
            ('PUT', lambda: client.put(LIST_URL, build_config(), format='json')),
            ('POST', lambda: client.post(RESET_URL)),
            ('DELETE', lambda: client.delete(RECORDS_URL)),
        ]
        for label, call in calls:
            with self.subTest(label):
                resp = call()
                self.assertEqual(resp.status_code, 403)
                body = resp.json()
                self.assertEqual(body['code'], 403)
                self.assertIn('权限', body['message'])


# ---------------------------------------------------------------- 中间件


@override_settings(ROOT_URLCONF=__name__)
class RateLimitMiddlewareTests(ConfigIsolationMixin, TestCase):
    """RateLimitMiddleware：每分钟窗口计数 / 429 + Retry-After / enabled=false 放行。"""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = RateLimitMiddleware(lambda req: JsonResponse({'ok': True}))

    def _get(self, url='/api/anything'):
        return self.middleware(self.factory.get(url))

    def test_third_request_blocked_with_retry_after(self):
        """假配置每分钟 2 次 → 第 3 次 429（中文 JSON + Retry-After）。"""
        save_config(build_config(per_minute={'anonymous': 2}))

        for i in (1, 2):
            with self.subTest(f'第 {i} 次放行'):
                self.assertEqual(self._get().status_code, 200)

        resp = self._get()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(
            json.loads(resp.content),
            {'code': 429, 'message': '请求过于频繁，请稍后再试', 'details': ''},
        )
        self.assertTrue(resp.has_header('Retry-After'))
        retry_after = int(resp['Retry-After'])
        self.assertGreaterEqual(retry_after, 1)
        self.assertLessEqual(retry_after, 60)

        # 已锁到窗口结束：第 4 次依旧 429
        self.assertEqual(self._get().status_code, 429)

        # 计数行：key 形如 api:<userId|ip>:<role>，窗口内计数
        row = RequestThrottle.objects.get(key__startswith='api:')
        self.assertEqual(row.key, 'api:127.0.0.1:anonymous')
        self.assertEqual(row.count, 3)
        self.assertIsNotNone(row.locked_until)

    def test_disabled_passes_through(self):
        """api.enabled=false → 不限流、不计数。"""
        save_config(build_config(per_minute={'anonymous': 1}, enabled=False))
        for _ in range(5):
            self.assertEqual(self._get().status_code, 200)
        self.assertEqual(RequestThrottle.objects.count(), 0)

    def test_non_api_path_not_throttled(self):
        """只拦 /api/ 前缀。"""
        save_config(build_config(per_minute={'anonymous': 1}))
        self.assertEqual(self._get('/admin/anything').status_code, 200)
        self.assertEqual(self._get('/static/app.js').status_code, 200)
        self.assertEqual(RequestThrottle.objects.count(), 0)

    def test_role_based_key_and_limit(self):
        """按「用户身份角色」计数：参赛代表 key = api:<userId>:player，限额独立。"""
        user = User.objects.create_user('player1', 'p1@example.com', 'playerpass12')
        competition = Competition.objects.create(name='春季商赛')
        CompetitionMembership.objects.create(
            user=user, competition=competition,
            identity=CompetitionMembership.Identity.PLAYER,
        )
        save_config(build_config(per_minute={'player': 1, 'anonymous': 1}))

        request = self.factory.get('/api/anything')
        request.user = user
        request.competition_id = competition.pk
        self.assertEqual(self.middleware(request).status_code, 200)

        request = self.factory.get('/api/anything')
        request.user = user
        request.competition_id = competition.pk
        self.assertEqual(self.middleware(request).status_code, 429)

        self.assertTrue(RequestThrottle.objects.filter(key=f'api:{user.pk}:player').exists())

    def test_cleanup_removes_expired_rows(self):
        """顺带清理过期计数行：只删「窗口过期且未锁定」的行。"""
        save_config(build_config(per_minute={'anonymous': 100}))
        now = timezone.now()
        RequestThrottle.objects.create(
            key='api:9:player', window_start=now - timedelta(seconds=700), count=1)
        RequestThrottle.objects.create(
            key='api:8:player', window_start=now - timedelta(seconds=700), count=1,
            locked_until=now + timedelta(seconds=60))  # 锁生效：保留
        RequestThrottle.objects.create(
            key='api:7:player', window_start=now, count=1)  # 新窗口：保留
        middleware_module._last_cleanup_at = 0.0  # 强制本次触发清理

        self.assertEqual(self._get().status_code, 200)
        keys = set(RequestThrottle.objects.values_list('key', flat=True))
        self.assertNotIn('api:9:player', keys)
        self.assertIn('api:8:player', keys)
        self.assertIn('api:7:player', keys)


class ResolveRoleTests(TestCase):
    """角色判定：superuser / 比赛身份 / 无身份 → anonymous。"""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user('u1', 'u1@example.com', 'password123')
        self.superuser = User.objects.create_superuser('root', 'root@example.com', 'rootpass123')
        self.competition = Competition.objects.create(name='春季商赛')

    def _request(self, user=None, competition_id=None, header=None):
        request = self.factory.get('/api/anything')
        if user is not None:
            request.user = user
        if competition_id is not None:
            request.competition_id = competition_id
        if header is not None:
            request.META['HTTP_X_COMPETITION_ID'] = str(header)
        return request

    def test_superuser_role(self):
        self.assertEqual(resolve_role(self._request(self.superuser)), 'superuser')

    def test_competition_identity_roles(self):
        for identity, role in (
            (CompetitionMembership.Identity.ADMIN, 'admin'),
            (CompetitionMembership.Identity.PLAYER, 'player'),
        ):
            with self.subTest(identity):
                CompetitionMembership.objects.filter(
                    user=self.user, competition=self.competition).delete()
                CompetitionMembership.objects.create(
                    user=self.user, competition=self.competition, identity=identity)
                # request.competition_id 与 X-Competition-Id 头两条路径都判定
                self.assertEqual(
                    resolve_role(self._request(self.user, competition_id=self.competition.pk)),
                    role)
                self.assertEqual(
                    resolve_role(self._request(self.user, header=self.competition.pk)),
                    role)

    def test_no_identity_is_anonymous(self):
        self.assertEqual(resolve_role(self._request(self.user)), 'anonymous')  # 无比赛上下文
        self.assertEqual(
            resolve_role(self._request(self.user, competition_id=self.competition.pk)),
            'anonymous')  # 有比赛但无身份
        self.assertEqual(resolve_role(self._request()), 'anonymous')  # 匿名


# ---------------------------------------------------------------- 登录限流读配置


@override_settings(ROOT_URLCONF=__name__)
class LoginThrottleConfigTests(ConfigIsolationMixin, TestCase):
    """登录限流优先读 RateLimitConfig 的 login 段（5 秒缓存）。"""

    def setUp(self):
        self.user = User.objects.create_user('bob', 'bob@example.com', 'goodpass123')
        self.client = APIClient()

    def _login(self, password):
        return self.client.post(
            '/api/auth/login', {'username': 'bob', 'password': password}, format='json')

    def test_login_limit_read_from_config(self):
        """改配置 failLimit=2 → 2 次失败即锁定，随后请求 429（即使密码正确）。"""
        save_config(build_config(login={'failLimit': 2, 'windowSeconds': 300, 'lockSeconds': 900}))

        self.assertEqual(self._login('bad').status_code, 401)
        self.assertEqual(self._login('bad').status_code, 401)

        resp = self._login('goodpass123')
        self.assertEqual(resp.status_code, 429)
        self.assertIn('锁定', resp.json()['message'])
        self.assertTrue(resp.has_header('Retry-After'))

    def test_login_limit_falls_back_to_settings(self):
        """取不到配置（从未保存过）→ 回退 settings 默认值。"""
        with self.settings(LOGIN_FAIL_LIMIT=2, LOGIN_FAIL_WINDOW_SECONDS=300, LOGIN_LOCK_SECONDS=900):
            self.assertEqual(self._login('bad').status_code, 401)
            self.assertEqual(self._login('bad').status_code, 401)
            self.assertEqual(self._login('goodpass123').status_code, 429)
