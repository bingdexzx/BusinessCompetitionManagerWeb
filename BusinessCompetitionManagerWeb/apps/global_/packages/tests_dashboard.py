"""比赛包 dashboard.json（仪表盘样式文件）导入测试。

2026-10 决策：仪表盘 = 比赛包内前端样式文件 + 绑定产业字段值（非自定义控件）。
这里直接单测 importer._load_dashboard（完整导入链路涉及建库，另有端到端冒烟）。
"""

import json
import tempfile
from pathlib import Path

from django.test import TestCase

from apps.global_.competitions.models import Competition
from apps.global_.packages import importer


def _write(root: Path, name: str, content: dict | str):
    path = root / name
    path.write_text(
        content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
        encoding='utf-8')


_VALID = {
    'title': '经营看板',
    'components': [
        {'id': 'revenue', 'type': 'number', 'title': '总营收',
         'bind': {'table': 'finance', 'fieldKey': 'revenue', 'aggregate': 'sum'}, 'suffix': '万'},
        {'id': 'rate', 'type': 'gauge', 'title': '产能利用率',
         'bind': {'table': 'entity', 'fieldKey': 'capacityRate', 'aggregate': 'latest', 'max': 100}},
        {'id': 'cash', 'type': 'table', 'title': '各公司现金',
         'bind': {'table': 'finance', 'fieldKey': 'cash', 'aggregate': 'latest'}},
        {'id': 'note', 'type': 'text', 'title': '规则说明', 'text': '……'},
    ],
}


class DashboardImportTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.competition = Competition.objects.create(
            name='仪表盘测试赛', code='DB', db_name='comp_dashboard_test')

    def _report(self) -> dict:
        return {'warnings': [], 'errors': [], 'dashboard': {}}

    def test_valid_dashboard_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, 'dashboard.json', _VALID)
            report = self._report()
            importer._load_dashboard(root, {}, self.competition, report)
            self.assertEqual(report['dashboard']['status'], 'OK')
            self.assertEqual(report['dashboard']['components'], 4)
            self.competition.refresh_from_db()
            self.assertEqual(self.competition.dashboard_layout['title'], '经营看板')
            self.assertEqual(len(self.competition.dashboard_layout['components']), 4)

    def test_custom_filename_via_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, 'board.json', _VALID)
            report = self._report()
            importer._load_dashboard(root, {'dashboard': 'board.json'}, self.competition, report)
            self.assertEqual(report['dashboard']['status'], 'OK')
            self.assertEqual(report['dashboard']['file'], 'board.json')

    def test_invalid_dashboard_errors_block(self):
        bad = {'title': 'x', 'components': [
            {'type': 'unknown', 'title': '坏组件', 'bind': {'table': 'entity', 'fieldKey': 'k'}},
            {'type': 'number', 'title': '缺绑定'},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, 'dashboard.json', bad)
            report = self._report()
            importer._load_dashboard(root, {}, self.competition, report)
            self.assertEqual(report['dashboard']['status'], 'INVALID')
            self.assertTrue(report['errors'])  # 校验失败进 errors，阻断导入
            self.assertEqual(report['warnings'], [])
            self.competition.refresh_from_db()
            self.assertEqual(self.competition.dashboard_layout, {})  # 不写入坏布局

    def test_missing_dashboard_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self._report()
            importer._load_dashboard(Path(tmp), {}, self.competition, report)
            self.assertEqual(report['dashboard']['status'], 'SKIPPED')
            self.assertEqual(report['warnings'], [])

    def test_industry_sections_saved(self):
        """按产业分屏：industries.<key> 各自组件独立校验与存储。"""
        doc = {
            'title': '经营看板',
            'components': _VALID['components'][:1],
            'industries': {
                'steel': {
                    'title': '钢铁产业看板',
                    'components': [
                        {'id': 'cap', 'type': 'number', 'title': '产能',
                         'bind': {'table': 'entity', 'fieldKey': 'steelCapacity',
                                  'aggregate': 'sum'}},
                    ],
                },
                'auto': {'components': [
                    {'id': 'sales', 'type': 'gauge', 'title': '销量达成',
                     'bind': {'table': 'finance', 'fieldKey': 'salesRate', 'max': 100}},
                ]},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, 'dashboard.json', doc)
            report = self._report()
            importer._load_dashboard(root, {}, self.competition, report)
            self.assertEqual(report['dashboard']['status'], 'OK')
            self.assertEqual(report['dashboard']['industries'], {'steel': 1, 'auto': 1})
            self.competition.refresh_from_db()
            layout = self.competition.dashboard_layout
            self.assertEqual(layout['industries']['steel']['title'], '钢铁产业看板')
            self.assertEqual(
                layout['industries']['steel']['components'][0]['bind']['fieldKey'],
                'steelCapacity')
            self.assertEqual(len(layout['industries']['auto']['components']), 1)

    def test_invalid_industry_component_rejected(self):
        """产业分区里组件不合法 → 整份布局不写入（INVALID + errors）。"""
        doc = {
            'components': [],
            'industries': {
                'steel': {'components': [{'type': 'number', 'title': '缺绑定'}]},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, 'dashboard.json', doc)
            report = self._report()
            importer._load_dashboard(root, {}, self.competition, report)
            self.assertEqual(report['dashboard']['status'], 'INVALID')
            self.assertTrue(any('industries.steel' in e for e in report['errors']))
            self.competition.refresh_from_db()
            self.assertEqual(self.competition.dashboard_layout, {})
