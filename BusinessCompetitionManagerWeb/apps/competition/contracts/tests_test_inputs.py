"""测试输入项插件：每个只含一个输入项、apply 无效果。

这些插件由 ``scripts/make_test_input_plugins.py`` 生成，用来在界面上逐项验证输入渲染与校验；
这里只断言「都能被加载、接口合法、无落账效果」。
"""

import glob
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from plugins_runtime import loader

PLUGIN_ROOT = Path(settings.MEDIA_ROOT) / 'plugins'


class TestInputPluginsTests(SimpleTestCase):
    def _files(self):
        return sorted(glob.glob(str(PLUGIN_ROOT / 'testinput_*' / '1.0.0' / 'contract_*.py')))

    def test_generated_plugins_exist(self):
        files = self._files()
        self.assertGreaterEqual(len(files), 29, f'只找到 {len(files)} 个测试插件')

    def test_each_plugin_has_single_input_and_no_effect(self):
        for path in self._files():
            module, problems = loader.load_plugin(path)
            self.assertEqual(problems, [], path)
            self.assertEqual(loader.validate_contract_plugin(module), [], path)
            self.assertEqual(len(module.INPUT_SCHEMA), 1, f'{path} 应只含一个输入项')
            self.assertEqual(module.apply(None), [], f'{path} 不应产生效果')
            self.assertEqual(module.check(None), [], f'{path} 不应有额外限制')
            self.assertTrue(module.CONTRACT_NAME.startswith('测试输入项：'), module.CONTRACT_NAME)
