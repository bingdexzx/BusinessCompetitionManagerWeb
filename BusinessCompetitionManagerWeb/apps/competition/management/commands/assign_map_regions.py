"""地图节点归属区域（2026-11）：把 MapNode.region 文本对到 Region 记录上。

用法：
    python manage.py assign_map_regions                  # 全部比赛
    python manage.py assign_map_regions --competition 49
    python manage.py assign_map_regions --only-empty     # 只补没填区域的节点
    python manage.py assign_map_regions --dry-run        # 只统计不写库
"""

from django.core.management.base import BaseCommand

from apps.common import context as ctx
from apps.competition.regions import nodes as region_nodes
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db


class Command(BaseCommand):
    help = '把地图节点归属到对应区域（按节点 region 文本建/匹配 Region，并规范化名称）'

    def add_arguments(self, parser):
        parser.add_argument('--competition', type=int, default=0, help='只处理指定比赛')
        parser.add_argument('--only-empty', action='store_true',
                            help='只处理还没填区域的节点，不覆盖已有归属')
        parser.add_argument('--dry-run', action='store_true', help='只统计，不写库')

    def handle(self, *args, **options):
        competition_id = options.get('competition') or 0
        only_empty = bool(options.get('only_empty'))
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
                if dry_run:
                    from apps.competition.basedata.models import MapNode

                    names = {region_nodes.normalize_region_name(n.region)
                             for n in MapNode.objects.all()}
                    names.discard('')
                    self.stdout.write(
                        f'比赛 {competition.id}: 待归属区域 {len(names)} 个 → '
                        f'{sorted(names)[:10]}')
                    continue
                summary = region_nodes.assign_nodes_to_regions(only_empty=only_empty)
                self.stdout.write(
                    f"比赛 {competition.id}: 新建区域 {len(summary['created'])}，"
                    f"命中已有 {len(summary['matched'])}，节点改写 {summary['updated']}，"
                    f"仍无区域 {len(summary['unassigned'])}，区域总数 {summary['regionCount']}")
                if summary['created']:
                    self.stdout.write(f"  新建：{'、'.join(summary['created'][:20])}")
            except Exception as exc:  # noqa: BLE001 —— 单库异常不影响其他比赛
                self.stderr.write(f'比赛 {competition.id}: 跳过（{type(exc).__name__}: {exc}）')
            finally:
                ctx.clear_request_context()

        self.stdout.write(self.style.SUCCESS('完成'))
