"""用户管理 API 测试（apps.global_.useradmin）。

- 不依赖根路由挂载：本模块自带 urlpatterns 模拟
  ``path('api/', include('apps.global_.useradmin.urls'))``，用
  ``override_settings(ROOT_URLCONF=__name__)`` 生效；
- 鉴权用 ``rest_framework.test.APIClient.force_authenticate``，不走真实 JWT。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import include, path
from rest_framework.test import APIClient

from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from apps.global_.schools.models import School

User = get_user_model()

# 模拟根路由挂载（生产中由根路由以 path('api/', include('apps.global_.useradmin.urls')) 引入）
urlpatterns = [
    path('api/', include('apps.global_.useradmin.urls')),
]

LIST_URL = '/api/users'


def detail_url(pk):
    return f'/api/users/{pk}'


def password_url(pk):
    return f'/api/users/{pk}/password'


@override_settings(ROOT_URLCONF=__name__)
class UserAdminBaseTestCase(TestCase):
    """公共夹具：系统超级管理员 admin、普通账号 member（带学校 + 比赛身份）。"""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='第一中学', region='华东')
        cls.other_school = School.objects.create(name='第二中学', region='华北')
        cls.admin = User.objects.create_superuser(
            'admin', 'admin@example.com', 'adminpass123',
        )
        cls.member = User.objects.create_user(
            'member', 'member@example.com', 'memberpass123',
            display_name='张三', school=cls.school,
        )
        cls.competition = Competition.objects.create(name='春季商赛')
        cls.membership = CompetitionMembership.objects.create(
            user=cls.member,
            competition=cls.competition,
            identity=CompetitionMembership.Identity.ADMIN,
            managed_companies=[7, 8],
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def api_as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


# ---------------------------------------------------------------- 列表 / 搜索


class UserListTests(UserAdminBaseTestCase):
    def test_list_page_shape(self):
        for i in range(3):
            User.objects.create_user(
                f'pageuser{i}', f'pageuser{i}@example.com', 'password123',
            )
        resp = self.client.get(LIST_URL, {'page': 1, 'pageSize': 2})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body.keys()), {'items', 'total', 'page', 'pageSize'})
        self.assertEqual(body['page'], 1)
        self.assertEqual(body['pageSize'], 2)
        self.assertEqual(body['total'], 5)  # admin + member + 3 个新账号
        self.assertEqual(len(body['items']), 2)

        # 翻完 3 页并集覆盖全部 5 个账号
        seen = [item['id'] for item in body['items']]
        for page in (2, 3):
            page_body = self.client.get(LIST_URL, {'page': page, 'pageSize': 2}).json()
            seen += [item['id'] for item in page_body['items']]
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(set(seen)), 5)

    def test_list_item_shape_and_memberships(self):
        resp = self.client.get(LIST_URL, {'pageSize': 100})
        self.assertEqual(resp.status_code, 200)
        items = resp.json()['items']
        member_item = next(item for item in items if item['username'] == 'member')
        self.assertEqual(
            set(member_item.keys()),
            {
                'id', 'username', 'displayName', 'email', 'school',
                'isSuperuser', 'isActive', 'createdAt', 'memberships',
            },
        )
        self.assertEqual(member_item['displayName'], '张三')
        self.assertEqual(member_item['email'], 'member@example.com')
        self.assertEqual(
            member_item['school'], {'id': self.school.pk, 'name': '第一中学'},
        )
        self.assertFalse(member_item['isSuperuser'])
        self.assertTrue(member_item['isActive'])
        self.assertTrue(member_item['createdAt'])
        self.assertEqual(
            member_item['memberships'],
            [{
                'competitionId': self.competition.pk,
                'identity': 'ADMIN',
                'managedCompanies': [7, 8],
            }],
        )
        # 无学校的账号 school 为 null
        admin_item = next(item for item in items if item['username'] == 'admin')
        self.assertIsNone(admin_item['school'])
        self.assertEqual(admin_item['memberships'], [])

    def test_search_by_username_display_name_email(self):
        User.objects.create_user(
            'searchtarget', 'unique@example.com', 'password123',
            display_name='李四',
        )
        # username 模糊
        body = self.client.get(LIST_URL, {'q': 'searchtar'}).json()
        self.assertEqual([u['username'] for u in body['items']], ['searchtarget'])
        self.assertEqual(body['total'], 1)
        # displayName 模糊
        body = self.client.get(LIST_URL, {'q': '李四'}).json()
        self.assertEqual([u['username'] for u in body['items']], ['searchtarget'])
        # email 模糊
        body = self.client.get(LIST_URL, {'q': 'unique@'}).json()
        self.assertEqual([u['username'] for u in body['items']], ['searchtarget'])
        # 无命中
        body = self.client.get(LIST_URL, {'q': '不存在的关键词'}).json()
        self.assertEqual(body['items'], [])
        self.assertEqual(body['total'], 0)

    def test_list_defaults(self):
        body = self.client.get(LIST_URL).json()
        self.assertEqual(body['page'], 1)
        self.assertEqual(body['pageSize'], 20)


# ---------------------------------------------------------------- 新建


class UserCreateTests(UserAdminBaseTestCase):
    def test_create_success(self):
        payload = {
            'username': 'newuser',
            'password': 'newpass1234',
            'displayName': '新用户',
            'email': 'new@example.com',
            'schoolId': self.other_school.pk,
            'isSuperuser': True,
        }
        resp = self.client.post(LIST_URL, payload, format='json')
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['username'], 'newuser')
        self.assertEqual(body['displayName'], '新用户')
        self.assertEqual(body['email'], 'new@example.com')
        self.assertEqual(body['school'], {'id': self.other_school.pk, 'name': '第二中学'})
        self.assertTrue(body['isSuperuser'])
        self.assertTrue(body['isActive'])
        self.assertEqual(body['memberships'], [])

        user = User.objects.get(username='newuser')
        self.assertTrue(user.check_password('newpass1234'))
        self.assertEqual(user.school_id, self.other_school.pk)

    def test_create_optional_fields(self):
        resp = self.client.post(
            LIST_URL,
            {'username': 'bareuser', 'password': 'barepass123', 'displayName': '裸账号'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertIsNone(body['email'])
        self.assertIsNone(body['school'])
        self.assertFalse(body['isSuperuser'])

    def test_create_validation_errors(self):
        base = {
            'username': 'validname', 'password': 'validpass123',
            'displayName': '有效', 'email': 'valid@example.com',
        }
        cases = [
            ({'username': ''}, '用户名'),
            ({'password': 'short'}, '密码'),
            ({'password': 'x' * 129}, '密码'),
            ({'password': None}, '密码'),
            ({'displayName': ''}, '显示名'),
            ({'email': 'not-an-email'}, '邮箱格式'),
            ({'schoolId': 999999}, '学校'),
        ]
        for override, keyword in cases:
            payload = {**base, **override}
            with self.subTest(override=override):
                resp = self.client.post(LIST_URL, payload, format='json')
                self.assertEqual(resp.status_code, 400)
                body = resp.json()
                self.assertEqual(body['code'], 400)
                self.assertIn(keyword, body['message'])
                self.assertEqual(body['details'], '')
                self.assertFalse(User.objects.filter(username='validname').exists())

    def test_create_duplicate_username(self):
        resp = self.client.post(
            LIST_URL,
            {'username': 'member', 'password': 'anotherpass1', 'displayName': '重复'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['message'], '用户名已存在')

    def test_create_duplicate_email_case_insensitive(self):
        resp = self.client.post(
            LIST_URL,
            {
                'username': 'emaildup', 'password': 'anotherpass1',
                'displayName': '邮箱重复', 'email': 'MEMBER@example.com',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['message'], '该邮箱已被使用')


# ---------------------------------------------------------------- 详情


class UserDetailTests(UserAdminBaseTestCase):
    def test_detail_shape(self):
        resp = self.client.get(detail_url(self.member.pk))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(
            set(body.keys()),
            {
                'id', 'username', 'displayName', 'email', 'school',
                'isSuperuser', 'isActive', 'createdAt', 'memberships',
            },
        )
        self.assertEqual(body['id'], self.member.pk)
        self.assertEqual(
            body['memberships'],
            [{
                'competitionId': self.competition.pk,
                'identity': 'ADMIN',
                'managedCompanies': [7, 8],
            }],
        )

    def test_detail_not_found(self):
        resp = self.client.get(detail_url(999999))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {'code': 404, 'message': '用户不存在', 'details': ''})


# ---------------------------------------------------------------- 修改


class UserUpdateTests(UserAdminBaseTestCase):
    def test_patch_fields(self):
        payload = {
            'displayName': '改名后',
            'email': 'changed@example.com',
            'schoolId': self.other_school.pk,
            'isActive': False,
            'isSuperuser': True,
        }
        resp = self.client.patch(detail_url(self.member.pk), payload, format='json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['displayName'], '改名后')
        self.assertEqual(body['email'], 'changed@example.com')
        self.assertEqual(body['school'], {'id': self.other_school.pk, 'name': '第二中学'})
        self.assertFalse(body['isActive'])
        self.assertTrue(body['isSuperuser'])

        self.member.refresh_from_db()
        self.assertEqual(self.member.display_name, '改名后')
        self.assertFalse(self.member.is_active)
        self.assertTrue(self.member.is_superuser)

    def test_patch_partial_and_clear_email_school(self):
        resp = self.client.patch(
            detail_url(self.member.pk),
            {'email': None, 'schoolId': None},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body['email'])
        self.assertIsNone(body['school'])
        self.member.refresh_from_db()
        self.assertIsNone(self.member.email)
        self.assertIsNone(self.member.school_id)

    def test_patch_email_conflict(self):
        resp = self.client.patch(
            detail_url(self.member.pk), {'email': 'ADMIN@example.com'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['message'], '该邮箱已被使用')

    def test_patch_invalid_values(self):
        cases = [
            ({'email': 'bad-email'}, '邮箱格式'),
            ({'schoolId': 999999}, '学校'),
            ({'isActive': 'yes'}, '是否启用'),
            ({'isSuperuser': 1}, '是否超级管理员'),
        ]
        for payload, keyword in cases:
            with self.subTest(payload=payload):
                resp = self.client.patch(detail_url(self.member.pk), payload, format='json')
                self.assertEqual(resp.status_code, 400)
                self.assertIn(keyword, resp.json()['message'])

    def test_patch_not_found(self):
        resp = self.client.patch(detail_url(999999), {'displayName': 'x'}, format='json')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['code'], 404)


# ---------------------------------------------------------------- 删除


class UserDeleteTests(UserAdminBaseTestCase):
    def test_delete_other_user(self):
        victim = User.objects.create_user(
            'victim', 'victim@example.com', 'victimpass1',
        )
        resp = self.client.delete(detail_url(victim.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'ok': True})
        self.assertFalse(User.objects.filter(pk=victim.pk).exists())

    def test_delete_self_forbidden(self):
        # 存在另一个超级管理员时：命中「不能删自己」
        User.objects.create_superuser('super2', 'super2@example.com', 'superpass12')
        resp = self.client.delete(detail_url(self.admin.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['message'], '不能删除当前登录账号')
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_delete_last_superuser_forbidden(self):
        # 唯一超级管理员删除自己：命中「不能删除最后一个系统超级管理员」
        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)
        resp = self.client.delete(detail_url(self.admin.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['message'], '不能删除最后一个超级管理员')
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_delete_not_found(self):
        resp = self.client.delete(detail_url(999999))
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------- 重置密码（顶号）


class UserResetPasswordTests(UserAdminBaseTestCase):
    def test_reset_password_bumps_token_version(self):
        target = User.objects.create_user(
            'resetme', 'resetme@example.com', 'oldpass1234',
        )
        before = target.token_version
        resp = self.client.post(
            password_url(target.pk), {'password': 'brandnewpass1'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'ok': True, 'message': '密码已重置'})

        target.refresh_from_db()
        self.assertEqual(target.token_version, before + 1)  # 顶号：已发 JWT 全部失效
        self.assertTrue(target.check_password('brandnewpass1'))
        self.assertFalse(target.check_password('oldpass1234'))

    def test_reset_password_validation(self):
        for password in (None, '', 'short', 'x' * 129):
            with self.subTest(password=password):
                resp = self.client.post(
                    password_url(self.member.pk), {'password': password}, format='json',
                )
                self.assertEqual(resp.status_code, 400)
                self.assertIn('密码', resp.json()['message'])
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('memberpass123'))

    def test_reset_password_not_found(self):
        resp = self.client.post(
            password_url(999999), {'password': 'whatever123'}, format='json',
        )
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------- 权限


class UserPermissionTests(UserAdminBaseTestCase):
    def test_non_superuser_forbidden_on_all_endpoints(self):
        client = self.api_as(self.member)  # 非超级管理员
        calls = [
            ('get', LIST_URL, None),
            ('post', LIST_URL, {'username': 'x', 'password': 'x' * 8, 'displayName': 'x'}),
            ('get', detail_url(self.admin.pk), None),
            ('patch', detail_url(self.admin.pk), {'displayName': 'x'}),
            ('delete', detail_url(self.member.pk), None),
            ('post', password_url(self.member.pk), {'password': 'x' * 8}),
        ]
        for method, url, payload in calls:
            with self.subTest(method=method, url=url):
                if payload is None:
                    resp = getattr(client, method)(url)
                else:
                    resp = getattr(client, method)(url, payload, format='json')
                self.assertEqual(resp.status_code, 403)
                body = resp.json()
                self.assertEqual(body['code'], 403)
                self.assertIn('权限', body['message'])
        # 一通拒绝后数据未被改动
        self.member.refresh_from_db()
        self.assertEqual(self.member.display_name, '张三')

    def test_unauthenticated_rejected(self):
        client = APIClient()
        resp = client.get(LIST_URL)
        self.assertEqual(resp.status_code, 401)
