"""用户管理权限收窄保护 + 顶号测试（Decision 2.3）。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


class UserPrivilegeReductionTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.admin = User.objects.create_superuser(
            'sadmin', 'sadmin@example.com', 'adminpass123')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _patch(self, pk, payload):
        return self.client.patch(f'/api/users/{pk}', payload, format='json')

    def test_demote_last_active_superuser_forbidden(self):
        resp = self._patch(self.admin.pk, {'isSuperuser': False})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['message'], '不能取消最后一个超级管理员')
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)

    def test_deactivate_last_active_superuser_forbidden(self):
        resp = self._patch(self.admin.pk, {'isActive': False})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['message'], '不能停用最后一个超级管理员')
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_demote_when_another_superuser_exists(self):
        other = User.objects.create_superuser('super2', 'super2@example.com', 'superpass12')
        resp = self._patch(self.admin.pk, {'isSuperuser': False})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_superuser)
        self.assertTrue(other.is_superuser)

    def test_privilege_reduction_bumps_token_version(self):
        User.objects.create_superuser('super2', 'super2@example.com', 'superpass12')
        target = User.objects.create_user('member', 'member@example.com', 'memberpass123')
        before = target.token_version
        resp = self._patch(target.pk, {'isActive': False})
        self.assertEqual(resp.status_code, 200, resp.content)
        target.refresh_from_db()
        self.assertEqual(target.token_version, before + 1)  # 顶号：已发 JWT 失效
        self.assertFalse(target.is_active)

    def test_promotion_does_not_bump_token_version(self):
        target = User.objects.create_user('member2', 'member2@example.com', 'memberpass123')
        before = target.token_version
        resp = self._patch(target.pk, {'isSuperuser': True})
        self.assertEqual(resp.status_code, 200, resp.content)
        target.refresh_from_db()
        self.assertEqual(target.token_version, before)  # 权限扩张不顶号
        self.assertTrue(target.is_superuser)
