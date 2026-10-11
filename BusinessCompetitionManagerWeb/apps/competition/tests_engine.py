"""引擎纯函数单元测试（公式求值 / 效果运算 / 编号格式）。"""

from django.test import SimpleTestCase

from apps.competition.contracts.engine import _effect_after
from apps.competition.industries.services import FormulaError, evaluate_formula


class FormulaTests(SimpleTestCase):
    def test_arithmetic_with_field_names(self):
        self.assertEqual(evaluate_formula('cash * 0.5', {'cash': 100}), 50)
        self.assertEqual(evaluate_formula('a + b * 2', {'a': 1, 'b': 3}), 7)
        self.assertEqual(evaluate_formula('(a + b) * 2', {'a': 1, 'b': 3}), 8)

    def test_missing_field_defaults_zero(self):
        self.assertEqual(evaluate_formula('unknown * 2', {}), 0)

    def test_unary_and_division(self):
        self.assertEqual(evaluate_formula('-a + 10', {'a': 4}), 6)
        self.assertEqual(evaluate_formula('a / 0', {'a': 4}), 0)

    def test_forbidden_expression_rejected(self):
        with self.assertRaises(FormulaError):
            evaluate_formula('__import__("os")', {})
        with self.assertRaises(FormulaError):
            evaluate_formula('a if a else b', {'a': 1, 'b': 2})


class EffectMathTests(SimpleTestCase):
    def test_add_sub_set(self):
        self.assertEqual(_effect_after(100, 'ADD', 50), 150)
        self.assertEqual(_effect_after(100, 'SUB', 50), 50)
        self.assertEqual(_effect_after(100, 'SET', 7), 7)

    def test_non_numeric_before_treated_as_zero(self):
        self.assertEqual(_effect_after(None, 'ADD', 5), 5)
        self.assertEqual(_effect_after('x', 'SUB', 5), -5)
