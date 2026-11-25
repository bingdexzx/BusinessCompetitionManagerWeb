"""批次一安全能力测试：修改密码 / 登录限流 / 版本下发。"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

User = get_user_model()


class ChangePasswordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='oldpass12345')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _post(self, old, new):
        return self.client.post('/api/auth/change-password',
                                {'oldPassword': old, 'newPassword': new}, format='json')

    def test_wrong_old_password(self):
        resp = self._post('wrong-pass', 'newpass12345')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('原密码', resp.json()['message'])

    def test_new_password_too_short(self):
        resp = self._post('oldpass12345', 'short')
        self.assertEqual(resp.status_code, 400)

    def test_new_same_as_old(self):
        resp = self._post('oldpass12345', 'oldpass12345')
        self.assertEqual(resp.status_code, 400)

    def test_change_password_bumps_token_version(self):
        before = self.user.token_version
        resp = self._post('oldpass12345', 'brandnewpass1')
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('brandnewpass1'))
        self.assertGreater(self.user.token_version, before)  # 顶号：旧 JWT 全部失效


@override_settings(LOGIN_FAIL_LIMIT=3, LOGIN_FAIL_WINDOW_SECONDS=300, LOGIN_LOCK_SECONDS=900)
class LoginThrottleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='bob', password='goodpass1234')
        self.client = APIClient()

    def _login(self, password):
        return self.client.post('/api/auth/login',
                                {'username': 'bob', 'password': password}, format='json')

    def test_lock_after_limit_failures(self):
        for _ in range(3):
            self.assertEqual(self._login('bad').status_code, 401)
        # 已锁定：即使密码正确也拒绝
        resp = self._login('goodpass1234')
        self.assertEqual(resp.status_code, 429)
        self.assertIn('锁定', resp.json()['message'])
        self.assertTrue(resp.has_header('Retry-After'))

    def test_success_resets_counter(self):
        self.assertEqual(self._login('bad').status_code, 401)
        self.assertEqual(self._login('goodpass1234').status_code, 200)
        # 清零后重新计数：再失败 2 次仍未锁定
        self.assertEqual(self._login('bad').status_code, 401)
        self.assertEqual(self._login('bad').status_code, 401)
        self.assertEqual(self._login('goodpass1234').status_code, 200)

    def test_keys_are_separate_per_username(self):
        for _ in range(3):
            self.assertEqual(self._login('bad').status_code, 401)
        resp = self.client.post('/api/auth/login',
                                {'username': 'other', 'password': 'x'}, format='json')
        self.assertEqual(resp.status_code, 401)  # 另一账号不受 bob 的锁影响


class VersionEndpointTests(TestCase):
    def test_version_exposed(self):
        resp = self.client.get('/api/version')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('version', resp.json())


class RegisterRealNameTests(TestCase):
    """注册必填「真实姓名」（落库 User.display_name）。"""

    URL = '/api/auth/register'

    def _post(self, **overrides):
        payload = {
            'username': 'reguser', 'password': 'RegPass12345',
            'email': 'reguser@test.local', 'displayName': '张三',
        }
        payload.update(overrides)
        return self.client.post(self.URL, payload, format='json')

    def test_real_name_required_blank(self):
        resp = self._post(displayName='')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('真实姓名', str(resp.json()))  # 字段级中文原因在 details
        self.assertFalse(User.objects.filter(username='reguser').exists())

    def test_real_name_required_missing_key(self):
        resp = self.client.post(self.URL, {
            'username': 'reguser', 'password': 'RegPass12345', 'email': 'reguser@test.local',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('真实姓名', str(resp.json()))
        self.assertFalse(User.objects.filter(username='reguser').exists())

    def test_real_name_saved_and_trimmed(self):
        resp = self._post(displayName='  李四  ')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['displayName'], '李四')
        user = User.objects.get(username='reguser')
        self.assertEqual(user.display_name, '李四')  # 首尾空格已去除

    def test_real_name_too_long_rejected(self):
        resp = self._post(displayName='名' * 101)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('100', str(resp.json()))
