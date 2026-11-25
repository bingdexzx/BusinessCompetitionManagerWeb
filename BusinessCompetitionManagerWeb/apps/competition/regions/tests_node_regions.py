"""地图节点归属区域（2026-11）：文本归一、建缺失 Region、显式映射、只补空值。"""

from django.test import TestCase

from apps.common import context as ctx
from apps.competition.basedata.models import MapNode, MapNodeType
from apps.competition.regions import nodes as region_nodes
from apps.competition.regions.models import Region
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class AssignNodesToRegionsTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='节点归属赛', code='NREG', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.node_type = MapNodeType.objects.create(name='城市')

    def _node(self, name, region=''):
        return MapNode.objects.create(name=name, region=region, node_type=self.node_type)

    def test_creates_missing_regions_and_normalizes_names(self):
        self._node('上海', ' 华东 ')
        self._node('杭州', '华东')
        self._node('成都', '西南')

        summary = region_nodes.assign_nodes_to_regions()

        self.assertEqual(sorted(summary['created']), ['华东', '西南'])
        self.assertEqual(summary['updated'], 1)  # 只有带空格的那条被改写
        self.assertEqual(Region.objects.count(), 2)
        self.assertEqual(MapNode.objects.get(name='上海').region, '华东')
        self.assertEqual(summary['unassigned'], [])
        self.assertEqual(summary['regionCount'], 2)

    def test_matches_existing_region_without_duplicating(self):
        Region.objects.create(name='华东')
        self._node('上海', '华东')
        summary = region_nodes.assign_nodes_to_regions()
        self.assertEqual(summary['created'], [])
        self.assertEqual(summary['matched'], ['华东'])
        self.assertEqual(Region.objects.filter(name='华东').count(), 1)

    def test_explicit_mapping_overrides_text(self):
        self._node('苏州', '')
        summary = region_nodes.assign_nodes_to_regions(
            mapping={'苏州': '华东', 1: '华南'})
        self.assertEqual(MapNode.objects.get(name='苏州').region, '华东')
        self.assertEqual(summary['created'], ['华东'])

    def test_only_empty_keeps_existing_assignment(self):
        self._node('上海', '华东')
        self._node('南京', '')
        summary = region_nodes.assign_nodes_to_regions(
            mapping={'上海': '华南', '南京': '华东'}, only_empty=True)
        self.assertEqual(MapNode.objects.get(name='上海').region, '华东')
        self.assertEqual(MapNode.objects.get(name='南京').region, '华东')
        self.assertEqual(summary['updated'], 1)

    def test_unassigned_nodes_reported(self):
        self._node('荒野', '')
        summary = region_nodes.assign_nodes_to_regions()
        self.assertEqual(summary['unassigned'], ['荒野'])
        self.assertEqual(summary['regionCount'], 0)

    def test_unknown_mapping_keys_reported(self):
        self._node('上海', '华东')
        summary = region_nodes.assign_nodes_to_regions(mapping={'不存在': '华东'})
        self.assertEqual(summary['unknown'], ['不存在'])

    def test_create_missing_false_skips_new_regions(self):
        self._node('上海', '华东')
        summary = region_nodes.assign_nodes_to_regions(create_missing=False)
        self.assertEqual(summary['created'], [])
        self.assertEqual(summary['unassigned'], ['上海'])
        self.assertEqual(MapNode.objects.get(name='上海').region, '华东')
