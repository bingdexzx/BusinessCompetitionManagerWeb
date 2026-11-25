"""字段治理（2026-11）：分组 / 排序 / 停用，仅超级管理员可改；停用字段不出现在公司字段表。"""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.competition.industries.formula_graph import (
    find_formula_cycles,
    formula_references,
)
from apps.competition.industries.services import (
    apply_industry_fields,
    evaluate_formula,
    flag_formula_cycles,
    recompute_company_fields,
)
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()



class RecomputeTests(TestCase):
    """公式重算：链深、循环、旧系统函数。"""

    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='重算赛', code='RCALC', db_name=ALIAS)
        ctx.set_competition_context(self.competition.pk, ALIAS)
        self.company = Company.objects.create(name='重算公司')

    def _field(self, key, formula='', calculated=False):
        return IndustryField.objects.create(
            field_key=key, name=key, field_type='NUMBER',
            data_table=IndustryField.DataTable.FINANCE,
            is_calculated=calculated, formula=formula)

    def _value(self, key):
        row = CompanyFieldValue.objects.filter(
            company=self.company, field_key=key, fiscal_year=None).first()
        return None if row is None else row.value

    def test_deep_chain_recomputes_to_stable(self):
        self._field('base')
        # 反向创建：e → d → c → b → base（对传播顺序最不利）
        for key, depends in (('e', 'd'), ('d', 'c'), ('c', 'b'), ('b', 'base')):
            self._field(key, f'{depends} + 1', calculated=True)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='base', value=10)

        recompute_company_fields(self.company)
        self.assertEqual(self._value('b'), 11)
        self.assertEqual(self._value('c'), 12)
        self.assertEqual(self._value('d'), 13)
        self.assertEqual(self._value('e'), 14)

    def test_cycle_terminates_without_error(self):
        self._field('x', 'y + 1', calculated=True)
        self._field('y', 'x + 1', calculated=True)
        changed = recompute_company_fields(self.company)  # 不抛异常
        self.assertGreaterEqual(changed, 0)
        self.assertIsNotNone(self._value('x'))

    def test_legacy_functions_in_field_formula(self):
        self._field('pop')
        self._field(
            'wage',
            'round(1000*(1+0.9*20/100)*log(pop+1000)*0.6)',
            calculated=True)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='pop', value=100)

        recompute_company_fields(self.company)
        expected = evaluate_formula(
            'round(1000*(1+0.9*20/100)*log(pop+1000)*0.6)', {'pop': 100})
        self.assertEqual(self._value('wage'), expected)

    def test_bad_formula_does_not_break_other_fields(self):
        self._field('base')
        self._field('broken', 'unknown_func(1)', calculated=True)
        self._field('ok', 'base * 2', calculated=True)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='base', value=7)

        recompute_company_fields(self.company)
        self.assertEqual(self._value('ok'), 14)


class FormulaGraphTests(SimpleTestCase):
    """公式依赖图：只认字段引用（排除函数名），环检测正确。"""

    def test_references_excludes_function_names(self):
        self.assertEqual(
            formula_references('round(a + b) * log(c, 10)'), {'a', 'b', 'c'})
        self.assertEqual(formula_references('IF(a < 1, b, c)'), {'a', 'b', 'c'})

    def test_dag_has_no_cycle(self):
        self.assertEqual(
            find_formula_cycles({'a': 'b + 1', 'b': 'c + 1', 'c': '1'}), [])

    def test_two_node_cycle(self):
        self.assertEqual(find_formula_cycles({'a': 'b + 1', 'b': 'a + 1'}), [['a', 'b']])

    def test_self_cycle(self):
        self.assertEqual(find_formula_cycles({'a': 'a + 1'}), [['a']])

    def test_three_node_cycle(self):
        cycles = find_formula_cycles({'a': 'b', 'b': 'c', 'c': 'a'})
        self.assertEqual(cycles, [['a', 'b', 'c']])


class FormulaCycleImportTests(TestCase):
    """导入时识别循环公式：打标 + 报告 + 拒绝计算；修正后恢复。"""

    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='循环赛', code='RCYC', db_name=ALIAS)
        ctx.set_competition_context(self.competition.pk, ALIAS)
        self.company = Company.objects.create(name='循环公司')

    def _spec(self, key, formula, calc=True):
        return {
            'key': key, 'name': key, 'type': 'NUMBER',
            'table': 'finance', 'formula': formula, 'calculated': calc,
        }

    def test_import_flags_cycle_and_refuses_to_compute(self):
        stats = apply_industry_fields(
            [self._spec('a', 'b + 1'), self._spec('b', 'a + 1')],
            plugin_key='cyc', plugin_version='1.0.0')
        self.assertEqual(stats['formulaCycles'], [['a', 'b']])

        self.assertTrue(IndustryField.objects.get(field_key='a').meta.get('formulaCycle'))
        self.assertTrue(IndustryField.objects.get(field_key='b').meta.get('formulaCycle'))

        # 拒绝计算：重算不写这两个字段
        changed = recompute_company_fields(self.company)
        self.assertEqual(changed, 0)
        self.assertEqual(
            CompanyFieldValue.objects.filter(
                company=self.company, field_key__in=['a', 'b']).count(), 0)

    def test_fixing_formula_clears_flag(self):
        apply_industry_fields(
            [self._spec('x', 'y + 1'), self._spec('y', 'x + 1')],
            plugin_key='cyc', plugin_version='1.0.0')
        self.assertTrue(IndustryField.objects.get(field_key='x').meta.get('formulaCycle'))

        # 修正 x 为常量后不再是环
        apply_industry_fields(
            [self._spec('x', '1'), self._spec('y', 'x + 1')],
            plugin_key='cyc', plugin_version='1.0.0')
        self.assertFalse(IndustryField.objects.get(field_key='x').meta.get('formulaCycle'))
        self.assertEqual(flag_formula_cycles(), [])
        recompute_company_fields(self.company)
        self.assertEqual(
            CompanyFieldValue.objects.get(
                company=self.company, field_key='x').value, 1)
        self.assertEqual(
            CompanyFieldValue.objects.get(
                company=self.company, field_key='y').value, 2)

    def test_acyclic_import_not_flagged(self):
        stats = apply_industry_fields(
            [self._spec('base', '', calc=False), self._spec('total', 'base * 2')],
            plugin_key='ok', plugin_version='1.0.0')
        self.assertEqual(stats['formulaCycles'], [])
        self.assertFalse(IndustryField.objects.get(field_key='total').meta.get('formulaCycle'))

class FieldSettingsTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='字段治理赛', code='FSET', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='治理公司')
        self.root = User.objects.create_user(
            username='fset_root', password='x' * 12, email='fset_root@test.local',
            is_superuser=True)
        self.player = User.objects.create_user(
            username='fset_player', password='x' * 12, email='fset_player@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)

        self.cash = IndustryField.objects.create(
            field_key='cash', name='现金', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY)
        self.stock = IndustryField.objects.create(
            field_key='stock', name='库存', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY)
        self.client = APIClient()
        self.client.force_authenticate(self.root)

    def _patch(self, key, payload):
        return self.client.patch(
            f'/api/competitions/{self.cid}/industry-fields/{key}', payload,
            format='json', HTTP_HOST='127.0.0.1')

    def test_group_order_and_active_defaults(self):
        response = self.client.get(
            f'/api/competitions/{self.cid}/industry-fields', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200)
        rows = {row['key']: row for row in response.json()}
        self.assertTrue(rows['cash']['active'])
        self.assertEqual(rows['cash']['group'], '')

    def test_set_group_and_order_and_active(self):
        self.assertEqual(self._patch('cash', {'group': '资产负债'}).status_code, 200)
        self.assertEqual(self._patch('cash', {'order': 1}).status_code, 200)
        self.assertEqual(self._patch('cash', {'active': False}).status_code, 200)
        ctx.set_competition_context(self.cid, ALIAS)
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.meta.get('group'), '资产负债')
        self.assertEqual(self.cash.meta.get('order'), 1)
        self.assertFalse(self.cash.meta.get('active'))
        self.assertTrue(FieldLog.objects.filter(
            field_key='cash', event=FieldLog.Event.SCHEMA_CHANGE).exists())

    def test_inactive_field_hidden_but_visible_with_flag(self):
        self._patch('stock', {'active': False})
        response = self.client.get(
            f'/api/competitions/{self.cid}/industry-fields?includeInactive=1',
            HTTP_HOST='127.0.0.1')
        self.assertIn('stock', [row['key'] for row in response.json()])

        ctx.set_competition_context(self.cid, ALIAS)
        response = self.client.get(
            f'/api/competitions/{self.cid}/companies/{self.company.id}/tables/entity',
            HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content)
        keys = [f['key'] for f in response.json()['fields']]
        self.assertIn('cash', keys)
        self.assertNotIn('stock', keys)

    def test_reorder_updates_meta_order(self):
        response = self.client.post(
            f'/api/competitions/{self.cid}/industry-fields/reorder',
            {'keys': ['stock', 'cash']}, format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content)
        ctx.set_competition_context(self.cid, ALIAS)
        self.stock.refresh_from_db()
        self.cash.refresh_from_db()
        self.assertEqual(self.stock.meta.get('order'), 1)
        self.assertEqual(self.cash.meta.get('order'), 2)

        response = self.client.get(
            f'/api/competitions/{self.cid}/industry-fields', HTTP_HOST='127.0.0.1')
        self.assertEqual([row['key'] for row in response.json()], ['stock', 'cash'])

    def test_non_superuser_cannot_manage_fields(self):
        client = APIClient()
        client.force_authenticate(self.player)
        response = client.patch(
            f'/api/competitions/{self.cid}/industry-fields/cash', {'active': False},
            format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 403)

    def test_invalid_order_rejected(self):
        response = self._patch('cash', {'order': 'abc'})
        self.assertEqual(response.status_code, 400)
