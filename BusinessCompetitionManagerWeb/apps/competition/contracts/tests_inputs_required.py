"""合同输入项一律必填（2026-11 决策）：缺任何一项都不允许创建/提交/修改。"""

from django.test import SimpleTestCase

from apps.competition.contracts import engine


class _FakeModule:
    PARTY_ROLES = [{'role': 'BUYER'}, {'role': 'SELLER'}]
    INPUT_SCHEMA = [
        {'key': 'quantity', 'label': '数量', 'type': 'NUMBER'},
        {'key': 'price', 'label': '单价', 'type': 'NUMBER'},
        {'key': 'note', 'label': '备注', 'type': 'TEXT'},
        {'key': 'urgent', 'label': '加急', 'type': 'BOOLEAN'},
    ]


PARTIES = [
    {'role': 'BUYER', 'companyId': 1},
    {'role': 'SELLER', 'companyId': 2},
]


class AllInputsRequiredTests(SimpleTestCase):
    def problems(self, inputs):
        return engine._validate_inputs(_FakeModule, PARTIES, inputs)

    def test_missing_number_is_rejected_without_required_flag(self):
        problems = self.problems({'price': 2, 'note': '说明', 'urgent': False})
        self.assertTrue(any('数量' in p for p in problems), problems)

    def test_missing_text_is_rejected(self):
        problems = self.problems({'quantity': 1, 'price': 2, 'urgent': True})
        self.assertTrue(any('备注' in p for p in problems), problems)

    def test_empty_string_and_empty_list_count_as_missing(self):
        problems = self.problems(
            {'quantity': 1, 'price': 0, 'note': '   ', 'urgent': False})
        self.assertTrue(any('备注' in p for p in problems), problems)

    def test_zero_is_valid_for_numbers(self):
        self.assertEqual(
            self.problems({'quantity': 0, 'price': 0, 'note': 'x', 'urgent': False}), [])

    def test_boolean_false_is_valid_but_none_is_not(self):
        self.assertEqual(
            self.problems({'quantity': 1, 'price': 1, 'note': 'x', 'urgent': False}), [])
        problems = self.problems({'quantity': 1, 'price': 1, 'note': 'x'})
        self.assertTrue(any('加急' in p for p in problems), problems)

    def test_all_filled_passes(self):
        self.assertEqual(
            self.problems({'quantity': 3, 'price': 9, 'note': '正常', 'urgent': True}), [])
