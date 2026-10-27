"""产业字段迁移测试：自动补「所在地」字段（旧系统 `_ensure_location_field` 口径）。

区域总览按「公司所在地 == 该区域下的地图节点名」把公司归入区域，因此这个字段必须存在。
"""

from django.test import TestCase

from apps.common import context as ctx
from apps.competition.industries.models import IndustryField
from apps.competition.industries.services import apply_industry_fields, ensure_location_field
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class LocationFieldTests(TestCase):
    databases = {'default', ALIAS}

    def setUp(self):
        ctx.set_competition_context(1, ALIAS)

    def tearDown(self):
        ctx.clear_request_context()

    def test_location_field_created_once(self):
        field = ensure_location_field(plugin_key='manufacturer', plugin_version='1.0.0')
        self.assertIsNotNone(field)
        self.assertEqual(field.field_key, 'location')
        self.assertEqual(field.name, '所在地')
        self.assertEqual(field.meta.get('isLocation'), True)
        self.assertEqual(field.field_type, IndustryField.FieldType.TEXT)

        # 幂等：已存在则不重复建
        self.assertIsNone(ensure_location_field(plugin_key='manufacturer'))
        self.assertEqual(IndustryField.objects.filter(field_key='location').count(), 1)

    def test_apply_industry_fields_ensures_location(self):
        apply_industry_fields(
            [{'key': 'cash', 'name': '现金', 'type': 'NUMBER', 'table': 'finance'}],
            plugin_key='manufacturer', plugin_version='1.0.0')
        self.assertTrue(IndustryField.objects.filter(field_key='location').exists())

    def test_plugin_defined_location_wins(self):
        """产业插件自己定义了 location 时，不要被自动补的「所在地」覆盖。"""
        apply_industry_fields(
            [{'key': 'location', 'name': '厂址', 'type': 'TEXT', 'table': 'entity'}],
            plugin_key='manufacturer', plugin_version='1.0.0')
        field = IndustryField.objects.get(field_key='location')
        self.assertEqual(field.name, '厂址')
        self.assertFalse(field.meta.get('isLocation'))
