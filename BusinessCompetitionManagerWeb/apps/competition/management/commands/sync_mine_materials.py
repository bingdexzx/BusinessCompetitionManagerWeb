"""把地图矿点按最近城市归入原料：默认只出报告，--apply 才写库。"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.common import context as ctx
from apps.competition import provisioning
from apps.competition.basedata import map_materials
from apps.global_.competitions.models import Competition


class Command(BaseCommand):
    help = '按「最近城市点位」把矿点归入原料（产地 + 按地点价格，价格先留空）'

    def add_arguments(self, parser):
        parser.add_argument('--competition', action='append', default=[], metavar='CID_OR_DB',
                            help='比赛 id 或比赛库名（可重复）；省略则处理全部比赛')
        parser.add_argument('--apply', action='store_true', help='真正写库（默认只输出报告）')

    def _targets(self, wanted: list[str]) -> list[Competition]:
        competitions = list(Competition.objects.using('default').all().order_by('id'))
        if not wanted:
            return competitions
        picked = []
        for item in wanted:
            token = str(item).strip()
            match = next(
                (c for c in competitions if str(c.id) == token or c.db_name == token), None)
            if match is None:
                raise CommandError(f'找不到比赛：{token}')
            if match not in picked:
                picked.append(match)
        return picked

    def handle(self, *args, **options):
        competitions = self._targets(options['competition'])
        if not competitions:
            self.stdout.write('没有可处理的比赛')
            return
        failures = 0
        for competition in competitions:
            alias = provisioning.ensure_competition_db(competition.db_name)
            previous = ctx.get_competition_id(), ctx.get_competition_alias()
            ctx.set_competition_context(competition.id, alias)
            try:
                report = map_materials.sync_mine_materials(apply=bool(options['apply']))
                self._print(competition, report)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                self.stderr.write(self.style.ERROR(f'[{competition.db_name}] 失败：{exc}'))
            finally:
                if previous[1]:
                    ctx.set_competition_context(*previous)
                else:
                    ctx.clear_request_context()
        if failures:
            raise CommandError(f'{failures} 个比赛处理失败')

    def _print(self, competition, report):
        head = '已写入' if report['applied'] else ('无变化' if not report['changed'] else '试算')
        tag = self.style.SUCCESS if report['applied'] else self.style.WARNING
        self.stdout.write(tag(f'[{competition.db_name}] {head}'))
        self.stdout.write(
            f'  矿点 {report["mines"]} 个　城市 {report["cities"]} 个　'
            f'矿种 {report["materials"]} 个（新建 {report["created"]} / 补齐 {report["updated"]} / '
            f'无变化 {report["unchanged"]}）')
        for detail in report['details']:
            mark = '已有' if detail['exists'] else '新建'
            cities = '、'.join(detail['cities'])
            self.stdout.write(f'  · {detail["name"]}（{detail["mines"]} 个矿点 → {cities}）[{mark}]')
        if report['unmatched']:
            self.stdout.write(self.style.WARNING(
                f'  有 {len(report["unmatched"])} 个矿点找不到城市：'
                + '、'.join(report['unmatched'][:8])))
        if not report['applied'] and report['changed']:
            self.stdout.write('  提示：加 --apply 才会写库')
