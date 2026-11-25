"""合同插件试跑（2026-11）：跑 check/apply 但绝不写库。"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.dryrun import dry_run_contract_plugin
from apps.competition.contracts.models import Contract, ContractFieldEffect
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from plugins_runtime.api import Effect
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class _GoodModule:
    CONTRACT_KEY = 'purchase'
    PARTY_ROLES = [{'role': 'buyer', 'label': '买方'}]
    INPUT_SCHEMA = [{'key': 'amount', 'label': '金额', 'type': 'NUMBER', 'min': 1}]

    @staticmethod
    def check(context):
        if context.company_field('buyer', 'cash', 0) < context.input('amount'):
            return ['买方资金不足']
        return []

    @staticmethod
    def apply(context):
        return [Effect(company='buyer', field='cash', op='SUB', value=context.input('amount'))]


class _BoomModule(_GoodModule):
    @staticmethod
    def check(context):
        raise ZeroDivisionError('boom')

    @staticmethod
    def apply(context):
        raise KeyError('boom')


class PluginDryRunTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='试跑测试赛', code='DRY', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='试跑公司', industry_key='manufacturer')
        IndustryField.objects.create(
            field_key='cash', name='现金', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='cash', fiscal_year=None, value=100, version=1)
        self.root = User.objects.create_user(
            username='dry_root', password='x' * 12, email='dry_root@test.local',
            is_superuser=True)
        self.player = User.objects.create_user(
            username='dry_player', password='x' * 12, email='dry_player@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        self.client = APIClient()
        self.client.force_authenticate(self.root)

    def test_dry_run_reports_effects_without_writing(self):
        with mock.patch.object(engine, 'load_contract_module', return_value=_GoodModule), \
                mock.patch('apps.competition.contracts.dryrun.contract_module_for',
                           return_value=_GoodModule):
            result = dry_run_contract_plugin(
                contract_type_key='purchase', inputs={'amount': 30})
        self.assertEqual(result['problems'], [])
        self.assertEqual(result['error'], '')
        self.assertEqual(len(result['effects']), 1)
        self.assertEqual(result['effects'][0]['field'], 'cash')
        self.assertEqual(result['inputs']['amount'], 30)
        # 不写任何东西
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertEqual(Contract.objects.count(), 0)
        self.assertEqual(ContractFieldEffect.objects.count(), 0)

    def test_dry_run_synthesizes_inputs_from_schema(self):
        with mock.patch('apps.competition.contracts.dryrun.contract_module_for',
                        return_value=_GoodModule):
            result = dry_run_contract_plugin(contract_type_key='purchase')
        self.assertEqual(result['inputs']['amount'], 1)  # NUMBER 取 min

    def test_dry_run_reports_check_problems(self):
        with mock.patch('apps.competition.contracts.dryrun.contract_module_for',
                        return_value=_GoodModule):
            result = dry_run_contract_plugin(
                contract_type_key='purchase', inputs={'amount': 999})
        self.assertEqual(result['problems'], ['买方资金不足'])

    def test_dry_run_wraps_plugin_exception(self):
        with mock.patch('apps.competition.contracts.dryrun.contract_module_for',
                        return_value=_BoomModule):
            result = dry_run_contract_plugin(contract_type_key='purchase')
        self.assertIn('插件执行失败', result['error'])

    def test_endpoint_requires_superuser(self):
        with mock.patch('apps.competition.contracts.dryrun.contract_module_for',
                        return_value=_GoodModule):
            response = self.client.post(
                f'/api/competitions/{self.cid}/contracts/plugins/purchase/dry-run',
                {}, format='json', HTTP_HOST='127.0.0.1')
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()['effects'])

            client = APIClient()
            client.force_authenticate(self.player)
            denied = client.post(
                f'/api/competitions/{self.cid}/contracts/plugins/purchase/dry-run',
                {}, format='json', HTTP_HOST='127.0.0.1')
            self.assertEqual(denied.status_code, 403)

    def test_endpoint_rejects_unknown_type(self):
        response = self.client.post(
            f'/api/competitions/{self.cid}/contracts/plugins/nope/dry-run',
            {}, format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 400)
