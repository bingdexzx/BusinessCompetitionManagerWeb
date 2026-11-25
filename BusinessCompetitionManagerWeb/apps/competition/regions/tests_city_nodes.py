"""其他节点归属城市（2026-11）：命名规律 + 同省近似 + 就近城市兜底。"""

from django.test import TestCase

from apps.common import context as ctx
from apps.competition.basedata.models import MapNode, MapNodeType
from apps.competition.regions import city_nodes
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class AssignNodesToCityTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='节点城市赛', code='NCITY', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.types = {
            name: MapNodeType.objects.create(name=name)
            for name in ('城市点位', '行政区域划分', '火车站', '高速口', '码头', '机场', '矿点')
        }
        self._node('城市点位', '北安', '北安省', 0, 0)
        self._node('城市点位', '樟港', '海湾省', 100, 0)
        self._node('城市点位', '松平', '长平省', 0, 100)

    def _node(self, type_name, name, region='', x=0.0, y=0.0):
        return MapNode.objects.create(
            name=name, region=region, node_type=self.types[type_name], x=x, y=y)

    def test_prefix_and_suffix_rules(self):
        station = self._node('火车站', '松平南', '长平省', 5, 105)
        port = self._node('码头', '樟港北港', '海湾省', 105, 5)
        airport = self._node('机场', '樟港国际机场', '海湾省', 110, 10)
        gate = self._node('高速口', '松平东', '长平省', 5, 95)

        summary = city_nodes.assign_nodes_to_cities()

        for node in (station, port, airport, gate):
            node.refresh_from_db()
        self.assertEqual(station.city, '松平')
        self.assertEqual(port.city, '樟港')
        self.assertEqual(airport.city, '樟港')
        self.assertEqual(gate.city, '松平')
        self.assertGreaterEqual(summary['updated'], 4)
        self.assertEqual(summary['rules'].get('prefix'), 4)

    def test_fuzzy_typo_matched_within_region(self):
        # 「漳港」是「樟港」的错别字：编辑距离 1，同省
        wrong = self._node('火车站', '漳港北', '海湾省', 100, 10)
        city_nodes.assign_nodes_to_cities()
        wrong.refresh_from_db()
        self.assertEqual(wrong.city, '樟港')

    def test_nearest_city_for_mine(self):
        mine = self._node('矿点', '煤', '长平省', 10, 90)
        city_nodes.assign_nodes_to_cities()
        mine.refresh_from_db()
        self.assertEqual(mine.city, '松平')

    def test_region_filled_from_city_when_missing(self):
        mine = self._node('矿点', '木材', '', 5, 95)
        city_nodes.assign_nodes_to_cities()
        mine.refresh_from_db()
        self.assertEqual(mine.city, '松平')
        self.assertEqual(mine.region, '长平省')

    def test_existing_city_not_overwritten_without_flag(self):
        node = self._node('火车站', '松平南', '长平省', 5, 105)
        MapNode.objects.filter(pk=node.pk).update(city='旧城市')
        city_nodes.assign_nodes_to_cities()
        node.refresh_from_db()
        self.assertEqual(node.city, '旧城市')

        city_nodes.assign_nodes_to_cities(overwrite=True)
        node.refresh_from_db()
        self.assertEqual(node.city, '松平')

    def test_dry_run_changes_nothing(self):
        node = self._node('火车站', '松平南', '长平省', 5, 105)
        summary = city_nodes.assign_nodes_to_cities(dry_run=True)
        node.refresh_from_db()
        self.assertEqual(node.city, '')
        self.assertEqual(summary['updated'], 1)
        self.assertTrue(summary['dryRun'])

    def test_city_and_region_nodes_skipped(self):
        city = MapNode.objects.get(name='松平')
        area = self._node('行政区域划分', '长平省', '长平省', 0, 0)
        city_nodes.assign_nodes_to_cities()
        city.refresh_from_db()
        area.refresh_from_db()
        self.assertEqual(city.city, '')
        self.assertEqual(area.city, '')
