"""插件输入项读取（2026-11）：原样值可能是字符串，提供类型安全的读取方法。"""

from django.test import SimpleTestCase

from plugins_runtime.api import ContractContext


class InputHelpersTests(SimpleTestCase):
    def setUp(self):
        self.ctx = ContractContext(inputs={
            '资金': '300000',          # 比赛包导入：数字也是字符串
            '数量': 5,                  # 界面录入：真数字
            '备注': '  你好  ',
            '加急': 'true',
            '挂牌': '否',
            '清单': {'a': 1},
            '空值': None,
            '坏数字': 'abc',
        })

    def test_input_returns_raw_value(self):
        self.assertEqual(self.ctx.input('资金'), '300000')
        self.assertEqual(self.ctx.input('数量'), 5)
        self.assertIsNone(self.ctx.input('不存在'))
        self.assertEqual(self.ctx.input('不存在', '默认'), '默认')

    def test_input_number_normalizes(self):
        self.assertEqual(self.ctx.input_number('资金'), 300000.0)
        self.assertEqual(self.ctx.input_number('数量'), 5.0)
        self.assertEqual(self.ctx.input_number('坏数字', 9), 9)
        self.assertEqual(self.ctx.input_number('空值', 1), 1)
        self.assertEqual(self.ctx.input_number('不存在'), 0.0)

    def test_input_text_normalizes(self):
        self.assertEqual(self.ctx.input_text('备注'), '你好')
        self.assertEqual(self.ctx.input_text('空值', '无'), '无')
        self.assertEqual(self.ctx.input_text('数量'), '5')

    def test_input_bool_normalizes(self):
        self.assertTrue(self.ctx.input_bool('加急'))
        self.assertFalse(self.ctx.input_bool('挂牌'))
        self.assertTrue(self.ctx.input_bool('不存在', True))
        self.assertFalse(self.ctx.input_bool('备注'))
