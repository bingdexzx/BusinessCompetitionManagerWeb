"""把其他节点归属到所属城市（2026-11）：按命名规律解析，解析不到就按坐标取就近城市。

用法：
    python manage.py assign_map_cities                       # 全部比赛
    python manage.py assign_map_cities --competition 51
    python manage.py assign_map_cities --node-types 矿点,码头
    python manage.py assign_map_cities --overwrite --dry-run
"""

from django.core.management.base import BaseCommand

from apps.common import context as ctx
from apps.competition.regions import city_nodes
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db


class Command(BaseCommand):
    help = '把车站/机场/码头/矿点等节点归属到所属城市（命名规律 + 就近城市兜底）'

    def add_arguments(self, parser):
        parser.add_argument('--competition', type=int, default=0, help='只处理指定比赛')
        parser.add_argument('--node-types', default='',
                            help='逗号分隔的节点类型名（默认除城市点位/行政区域划分外全部）')
        parser.add_argument('--overwrite', action='store_true', help='覆盖已有 city')
        parser.add_argument('--no-nearest', action='store_true', help='不用就近城市兜底')
        parser.add_argument('--dry-run', action='store_true', help='只统计不写库')

    def handle(self, *args, **options):
        competition_id = options.get('competition') or 0
        raw_types = str(options.get('node_types') or '').strip()
        node_types = [item.strip() for item in raw_types.split(',') if item.strip()]
        overwrite = bool(options.get('overwrite'))
        use_nearest = not bool(options.get('no_nearest'))
        dry_run = bool(options.get('dry_run'))

        competitions = Competition.objects.using('default').all()
        if competition_id:
            competitions = competitions.filter(pk=competition_id)

        for competition in competitions:
            if not competition.db_name:
                continue
            try:
                register_competition_db(competition.db_name)
                ctx.set_competition_context(competition.id, competition.db_name)
                summary = city_nodes.assign_nodes_to_cities(
                    node_types=node_types or None, overwrite=overwrite,
                    use_nearest=use_nearest, dry_run=dry_run)
                self.stdout.write(
                    f"比赛 {competition.id}: 城市 {summary['cities']} 个，"
                    f"归属 {summary['updated']} 个节点，规则分布 {summary['rules']}，"
                    f"未归属 {len(summary['unmatched'])}"
                    + ('（dry-run 未写库）' if dry_run else ''))
                for row in summary['unmatched'][:10]:
                    self.stdout.write(f"  未归属：{row['type']} / {row['name']}")
            except Exception as exc:  # noqa: BLE001 —— 单库异常不影响其他比赛
                self.stderr.write(f'比赛 {competition.id}: 跳过（{type(exc).__name__}: {exc}）')
            finally:
                ctx.clear_request_context()

        self.stdout.write(self.style.SUCCESS('完成'))
