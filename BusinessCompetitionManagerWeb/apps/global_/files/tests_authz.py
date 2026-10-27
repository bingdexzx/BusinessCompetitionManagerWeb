"""文件读取鉴权与白名单测试（Decision 2.2）。"""

import gc
import shutil
import tempfile
import time
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient


class ServeFileAuthzTests(TestCase):
    databases = {'default'}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_dir = Path(tempfile.mkdtemp(prefix='bcm-files-authz-'))
        cls._override = override_settings(MEDIA_ROOT=cls.media_dir)
        cls._override.enable()
        cls.addClassCleanup(cls._cleanup)
        cls.addClassCleanup(cls._override.disable)

    @classmethod
    def _cleanup(cls):
        for _ in range(10):
            gc.collect()
            shutil.rmtree(cls.media_dir, ignore_errors=True)
            if not cls.media_dir.exists():
                return
            time.sleep(0.1)
        shutil.rmtree(cls.media_dir, ignore_errors=True)

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='fileviewer', password='x' * 12, email='fileviewer@test.local')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _write(self, rel: str, content: bytes = b'x'):
        p = self.media_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def test_view_requires_login(self):
        anon = APIClient()
        resp = anon.get('/api/files/view/uploads/whatever.png')
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_whitelist_blocks_non_whitelisted_dirs(self):
        self._write('uploads/ok.txt')
        self._write('map_backgrounds/1/bg.png')
        self._write('messages/2026/10/pic.png')
        self._write('plugins/evil.txt')
        self._write('packages/pkg.txt')
        self._write('secret.txt')

        # 白名单可读
        for url, content in (
            ('/api/files/view/uploads/ok.txt', b'x'),
            ('/api/files/view/map_backgrounds/1/bg.png', b'x'),
            ('/api/files/view/messages/2026/10/pic.png', b'x'),
        ):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(b''.join(resp.streaming_content), content)

        # 白名单外（plugins / packages / 根目录）→ 404
        for bad in (
            '/api/files/view/plugins/evil.txt',
            '/api/files/view/packages/pkg.txt',
            '/api/files/view/secret.txt',
        ):
            with self.subTest(bad=bad):
                resp = self.client.get(bad)
                self.assertEqual(resp.status_code, 404, f'{bad} -> {resp.content}')
