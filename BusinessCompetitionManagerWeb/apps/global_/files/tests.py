"""文件上传服务测试（apps.global_.files）。

- 本 app 模型在全局库（default），`databases={'default'}` 即可；
- Competition/Membership 的创建方式对齐 apps/competition/regions/tests.py，
  但比赛上下文中间件会按 Competition.db_name 注册比赛库 alias，故 db_name
  仍须带 `comp_` 前缀（alias 仅注册不连接，测试不触碰比赛库）；
- MEDIA_ROOT 用临时目录（override_settings），不污染真实 media。
"""

import gc
import json
import shutil
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.global_.competitions.models import Competition
from apps.global_.files import views as files_views
from apps.global_.files.models import MapBackground
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

# 本 app 全部模型走全局库 default，测试本身不需要比赛库；但 /api/competitions/{cid}/...
# 的 CompetitionContextMiddleware 会在请求期按 Competition.db_name 注册比赛库 alias。
# Django 的 SimpleTestCase._add/_remove_databases_failures 会在类开始/结束时对
# 「不在 cls.databases 里的连接」包装/还原连接方法——若 alias 首次出现在类运行期间，
# 两遍遍历的 alias 集合不一致，类清理时会报
# `AttributeError: 'function' object has no attribute 'wrapped'`。
# 故与 apps/competition/regions/tests.py 一致：**导入期**注册 alias（仅注册不连接），
# 保证包装/还原对称；databases 仍只声明 {'default'}，不建比赛测试库。
COMP_ALIAS = 'comp_files_unittest'
register_competition_db(COMP_ALIAS)

PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'fake-png-body' * 8


class MediaRootTestCase(TestCase):
    """测试基类：每个测试类用独立临时 MEDIA_ROOT（类清理必跑，不污染真实 media）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_dir = Path(tempfile.mkdtemp(prefix='bcm-files-media-'))
        cls._media_override = override_settings(MEDIA_ROOT=cls.media_dir)
        cls._media_override.enable()
        # 类清理按 LIFO 执行：先撤 override 再删临时目录（注册在最后、最先执行）
        cls.addClassCleanup(cls._cleanup_media_dir)
        cls.addClassCleanup(cls._media_override.disable)

    @classmethod
    def _cleanup_media_dir(cls):
        """删除临时 MEDIA_ROOT（Windows 下偶发句柄占用 → 有限重试后再删）。"""
        for _ in range(10):
            gc.collect()
            shutil.rmtree(cls.media_dir, ignore_errors=True)
            if not cls.media_dir.exists():
                return
            time.sleep(0.1)
        shutil.rmtree(cls.media_dir, ignore_errors=True)


def _png(name: str = 'pic.png') -> SimpleUploadedFile:
    return SimpleUploadedFile(name, PNG_BYTES, content_type='image/png')


class FileUploadTests(MediaRootTestCase):
    """`POST /api/files/upload` 通用上传 + `GET /api/files/view/<path>` 读取。"""

    databases = {'default'}

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='uploader', password='x' * 12, email='uploader@test.local')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_upload_success(self):
        content = PNG_BYTES
        resp = self.client.post(
            '/api/files/upload',
            {'file': SimpleUploadedFile('照片.png', content, content_type='image/png')},
            format='multipart')
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertEqual(
            set(data), {'url', 'fileName', 'size', 'contentType', 'uploadedAt'})
        self.assertTrue(data['url'].startswith('/api/files/view/uploads/'), data['url'])
        self.assertEqual(data['fileName'], '照片.png')
        self.assertEqual(data['size'], len(content))
        self.assertEqual(data['contentType'], 'image/png')
        self.assertTrue(data['uploadedAt'])

        # 磁盘落位：MEDIA_ROOT/uploads/YYYY/MM/<uuid>.<ext>
        rel = data['url'].removeprefix('/api/files/view/')
        saved = self.media_dir / rel
        self.assertTrue(saved.is_file(), saved)
        self.assertEqual(saved.read_bytes(), content)
        self.assertIn('/uploads/', f'/{rel}')
        self.assertTrue(saved.name.endswith('.png'))

        # 读取接口返回文件本体 + content-type（FileResponse 为流式响应，读 streaming_content）
        resp = self.client.get(data['url'])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('Content-Type'), 'image/png')
        self.assertEqual(b''.join(resp.streaming_content), content)

    def test_upload_rejects_bad_extension(self):
        resp = self.client.post(
            '/api/files/upload',
            {'file': SimpleUploadedFile('evil.exe', b'MZ', content_type='application/octet-stream')},
            format='multipart')
        self.assertEqual(resp.status_code, 400, resp.content)
        data = resp.json()
        self.assertEqual(data['code'], 400)
        self.assertTrue(data['message'])
        self.assertIn('details', data)

    def test_upload_rejects_oversize(self):
        # 上限常量即契约：≤100MB
        self.assertEqual(files_views.MAX_UPLOAD_SIZE, 100 * 1024 * 1024)
        # 用小上限触发同一拒绝路径（避免测试进程搬 100MB 载荷）
        with mock.patch.object(files_views, 'MAX_UPLOAD_SIZE', 1024):
            resp = self.client.post(
                '/api/files/upload',
                {'file': SimpleUploadedFile('big.zip', b'x' * 2048, content_type='application/zip')},
                format='multipart')
        self.assertEqual(resp.status_code, 400, resp.content)
        data = resp.json()
        self.assertEqual(data['code'], 400)
        self.assertTrue(data['message'])

    def test_upload_requires_login(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(
            '/api/files/upload', {'file': _png()}, format='multipart')
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertEqual(resp.json()['code'], 401)

    def test_view_rejects_path_traversal(self):
        # 真实上传一份文件作对照（正常读取已在 test_upload_success 覆盖）
        for bad in (
            '/api/files/view/../secret.txt',
            '/api/files/view/uploads/../../secret.txt',
            '/api/files/view/uploads/%2e%2e/%2e%2e/secret.txt',
        ):
            resp = self.client.get(bad)
            self.assertIn(resp.status_code, (400, 404), f'{bad} -> {resp.content}')
            self.assertIn(resp.json()['code'], (400, 404))

    def test_view_missing_file_is_404(self):
        resp = self.client.get('/api/files/view/uploads/2026/01/nope.png')
        self.assertEqual(resp.status_code, 404, resp.content)


class MapBackgroundTests(MediaRootTestCase):
    """`/api/competitions/{cid}/files/map-background` GET/POST/PATCH/DELETE。"""

    databases = {'default'}

    def setUp(self):
        user_model = get_user_model()
        self.competition = Competition.objects.create(
            name='文件测试赛', code='FILES', db_name=COMP_ALIAS)
        self.cid = self.competition.pk
        self.manager = user_model.objects.create_user(
            username='filemgr', password='x' * 12, email='filemgr@test.local', is_superuser=True)
        from apps.global_.memberships.models import CompetitionMembership
        CompetitionMembership.objects.create(
            user=self.manager, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN)
        self.player = user_model.objects.create_user(
            username='fileplayer', password='x' * 12, email='fileplayer@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def _url(self) -> str:
        return f'/api/competitions/{self.cid}/files/map-background'

    def test_map_background_default_is_empty(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), {'url': '', 'transform': None})

    def test_map_background_upload_lifecycle(self):
        # POST：上传背景图（form 字段 transform 随附）
        resp = self.client.post(
            self._url(),
            {'file': _png('bg.png'), 'transform': json.dumps({'scale': 2, 'x': 10, 'y': 20})},
            format='multipart')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(
            data['url'].startswith(f'/api/files/view/map_backgrounds/{self.cid}/'), data['url'])
        self.assertEqual(data['transform'], {'scale': 2, 'x': 10, 'y': 20})

        # 磁盘落位 + GET 返回持久化结果
        rel = data['url'].removeprefix('/api/files/view/')
        saved = self.media_dir / rel
        self.assertTrue(saved.is_file(), saved)
        self.assertEqual(self.client.get(self._url()).json(), data)
        row = MapBackground.objects.get(competition_id=self.cid)
        self.assertEqual(row.file_path, rel)
        self.assertEqual(row.transform, {'scale': 2, 'x': 10, 'y': 20})

        # PATCH：只改 transform
        resp = self.client.patch(
            self._url(), {'transform': {'scale': 0.5, 'x': -3, 'y': 4}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['transform'], {'scale': 0.5, 'x': -3, 'y': 4})
        self.assertEqual(resp.json()['url'], data['url'])
        row.refresh_from_db()
        self.assertEqual(row.transform, {'scale': 0.5, 'x': -3, 'y': 4})

        # DELETE：清记录 + 尽力删磁盘文件
        resp = self.client.delete(self._url())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), {'ok': True})
        self.assertFalse(MapBackground.objects.filter(competition_id=self.cid).exists())
        self.assertFalse(saved.exists())
        self.assertEqual(
            self.client.get(self._url()).json(), {'url': '', 'transform': None})

    def test_map_background_url_mode(self):
        # POST：JSON {url, transform}（外链图片模式）
        resp = self.client.post(
            self._url(),
            {'url': 'https://example.com/map.png', 'transform': {'scale': 1.5}},
            format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['url'], 'https://example.com/map.png')
        self.assertEqual(data['transform'], {'scale': 1.5, 'x': 0, 'y': 0})

        # PATCH：transform 置空（自动适配）
        resp = self.client.patch(self._url(), {'transform': None}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.json()['transform'])
        self.assertEqual(
            self.client.get(self._url()).json(),
            {'url': 'https://example.com/map.png', 'transform': None})

        # PATCH：缺 transform → 400
        resp = self.client.patch(self._url(), {'oops': 1}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)

        # POST：既无文件也无 url → 400
        resp = self.client.post(self._url(), {'transform': None}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)

        # DELETE 无文件模式同样清除记录
        resp = self.client.delete(self._url())
        self.assertEqual(resp.json(), {'ok': True})
        self.assertFalse(MapBackground.objects.filter(competition_id=self.cid).exists())

    def test_map_background_rejects_non_image_upload(self):
        resp = self.client.post(
            self._url(),
            {'file': SimpleUploadedFile('bg.pdf', b'%PDF-1.4', content_type='application/pdf')},
            format='multipart')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['code'], 400)

    def test_map_background_write_requires_manager(self):
        self.client.force_authenticate(self.player)
        for resp in (
            self.client.post(self._url(), {'file': _png()}, format='multipart'),
            self.client.post(self._url(), {'url': 'https://example.com/a.png'}, format='json'),
            self.client.patch(self._url(), {'transform': {'scale': 1}}, format='json'),
            self.client.delete(self._url()),
        ):
            self.assertEqual(resp.status_code, 403, resp.content)
            data = resp.json()
            self.assertEqual(data['code'], 403)
            self.assertTrue(data['message'])
            self.assertIn('details', data)
        # 读不受影响
        self.assertEqual(self.client.get(self._url()).status_code, 200)
        self.assertFalse(MapBackground.objects.filter(competition_id=self.cid).exists())


class MessageImageUploadTests(MediaRootTestCase):
    """`POST /api/messages/upload-image` 站内信图片上传。"""

    databases = {'default'}

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='msguser', password='x' * 12, email='msguser@test.local')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_message_image_upload_success(self):
        resp = self.client.post(
            '/api/messages/upload-image', {'file': _png('sticker.gif'.replace('gif', 'png'))},
            format='multipart')
        self.assertEqual(resp.status_code, 201, resp.content)
        url = resp.json()['url']
        self.assertTrue(url.startswith('/api/files/view/messages/'), url)
        rel = url.removeprefix('/api/files/view/')
        saved = self.media_dir / rel
        self.assertTrue(saved.is_file(), saved)
        self.assertEqual(saved.read_bytes(), PNG_BYTES)

    def test_message_image_rejects_non_image(self):
        resp = self.client.post(
            '/api/messages/upload-image',
            {'file': SimpleUploadedFile('doc.pdf', b'%PDF-1.4', content_type='application/pdf')},
            format='multipart')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['code'], 400)

    def test_message_image_rejects_over_5mb(self):
        self.assertEqual(files_views.MESSAGE_IMAGE_MAX_SIZE, 5 * 1024 * 1024)
        big = SimpleUploadedFile(
            'big.png', b'x' * (5 * 1024 * 1024 + 1), content_type='image/png')
        resp = self.client.post('/api/messages/upload-image', {'file': big}, format='multipart')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['code'], 400)

    def test_message_image_requires_login(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(
            '/api/messages/upload-image', {'file': _png()}, format='multipart')
        self.assertEqual(resp.status_code, 401, resp.content)
