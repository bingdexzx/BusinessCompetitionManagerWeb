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
        with self.assertRaises(FormulaError):
            evaluate_formula('open("x")', {})

    def test_legacy_functions(self):
        # 旧系统 calcGraph 公式用到的函数都要能算
        self.assertEqual(evaluate_formula('round(1.234, 2)', {}), 1.23)
        self.assertEqual(evaluate_formula('roundTo(1.235, 2)', {}), 1.24)
        self.assertEqual(evaluate_formula('min(3, 1, 2)', {}), 1)
        self.assertEqual(evaluate_formula('max(3, 1, 2)', {}), 3)
        self.assertEqual(evaluate_formula('abs(-5)', {}), 5)
        self.assertEqual(evaluate_formula('sqrt(400)', {}), 20)
        self.assertEqual(evaluate_formula('pow(100, 0.5)', {}), 10)
        self.assertAlmostEqual(evaluate_formula('log(100, 10)', {}), 2.0)
        self.assertAlmostEqual(evaluate_formula('log(1)', {}), 0.0)
        self.assertEqual(evaluate_formula('floor(1.9)', {}), 1)
        self.assertEqual(evaluate_formula('ceil(1.1)', {}), 2)
        self.assertEqual(evaluate_formula('int(1.9)', {}), 1)

    def test_if_and_comparisons(self):
        self.assertEqual(evaluate_formula('IF(1 < 2, 5, 9)', {}), 5)
        self.assertEqual(evaluate_formula('IF(a >= 10, 1, 0)', {'a': 5}), 0)
        self.assertEqual(evaluate_formula('IF(a == 5 and b != 0, 7, 8)', {'a': 5, 'b': 1}), 7)
        self.assertEqual(evaluate_formula('IF(a > 5 or b > 5, 1, 0)', {'a': 1, 'b': 9}), 1)

    def test_domain_errors_return_zero(self):
        self.assertEqual(evaluate_formula('sqrt(-1)', {}), 0)
        self.assertEqual(evaluate_formula('log(0)', {}), 0)
        self.assertEqual(evaluate_formula('1 / 0', {}), 0)

    def test_unknown_function_rejected(self):
        with self.assertRaises(FormulaError):
            evaluate_formula('sum(1, 2)', {})


class EffectMathTests(SimpleTestCase):
    def test_add_sub_set(self):
        self.assertEqual(_effect_after(100, 'ADD', 50), 150)
        self.assertEqual(_effect_after(100, 'SUB', 50), 50)
        self.assertEqual(_effect_after(100, 'SET', 7), 7)

    def test_non_numeric_before_treated_as_zero(self):
        self.assertEqual(_effect_after(None, 'ADD', 5), 5)
        self.assertEqual(_effect_after('x', 'SUB', 5), -5)
