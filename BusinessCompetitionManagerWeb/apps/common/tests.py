"""公共层单测：脱敏（§14.3）、设备解析（§14.4）。"""

from django.test import SimpleTestCase

from apps.common.devices import UNKNOWN_DEVICE, localize_snapshot, parse_user_agent
from apps.common.redaction import REDACTED, digest, redact


class RedactionTests(SimpleTestCase):
    def test_sensitive_keys_redacted(self):
        data = {
            'username': 'alice',
            'password': 'p@ss',
            'token': 'abc',
            'Authorization': 'Bearer x',
            'invite_code': 'XYZ',
            'nested': {'secret_key': 's', 'ok': 1},
        }
        out = redact(data)
        self.assertEqual(out['username'], 'alice')
        self.assertEqual(out['password'], REDACTED)
        self.assertEqual(out['token'], REDACTED)
        self.assertEqual(out['Authorization'], REDACTED)
        self.assertEqual(out['invite_code'], REDACTED)
        self.assertEqual(out['nested']['secret_key'], REDACTED)
        self.assertEqual(out['nested']['ok'], 1)

    def test_digest_json_body(self):
        text = digest(b'{"username": "a", "password": "raw"}')
        self.assertIn(REDACTED, text)
        self.assertNotIn('raw', text)

    def test_digest_unparsed_text_never_stored(self):
        self.assertTrue(digest('password=raw&x=1').startswith('<unparsed'))


class DeviceParseTests(SimpleTestCase):
    def test_windows_chrome(self):
        parsed = parse_user_agent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
        )
        self.assertEqual(parsed['os'], 'Windows 10/11')
        self.assertEqual(parsed['browser'], 'Chrome')

    def test_unknown(self):
        parsed = parse_user_agent('')
        self.assertEqual(parsed['os'], UNKNOWN_DEVICE)
        self.assertEqual(parsed['browser'], UNKNOWN_DEVICE)
        self.assertEqual(UNKNOWN_DEVICE, '未知')
        # 历史数据里存的 'Unknown' 展示时也要变成中文
        self.assertEqual(localize_snapshot({'os': 'Unknown', 'browser': ''})['browser'], '未知')
