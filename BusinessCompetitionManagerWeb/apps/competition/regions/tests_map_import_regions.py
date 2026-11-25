"""地图导入后自动把节点归属到区域（2026-11 集成测试）。"""

from django.test import TestCase

from apps.common import context as ctx
from apps.competition.basedata.map_import import import_geojson
from apps.competition.basedata.models import MapNode
from apps.competition.regions.models import Region
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


def _point(name, region, x, y):
    return {
        'type': 'Feature',
        'geometry': {'type': 'Point', 'coordinates': [x, y]},
        'properties': {'name': name, 'nodeType': '城市', 'region': region},
    }


class MapImportRegionSyncTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='导入归区赛', code='MREG', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

    def test_import_creates_region_records(self):
        payload = {
            'type': 'FeatureCollection',
            'features': [
                _point('上海', ' 华东 ', 121.47, 31.23),
                _point('杭州', '华东', 120.15, 30.27),
                _point('成都', '西南', 104.07, 30.57),
            ],
        }
        report = import_geojson(payload)

        self.assertIn('regionsSync', report)
        self.assertEqual(sorted(report['regionsSync']['created']), ['华东', '西南'])
        self.assertEqual(Region.objects.count(), 2)
        self.assertEqual(MapNode.objects.get(name='上海').region, '华东')
        self.assertEqual(MapNode.objects.get(name='杭州').region, '华东')
