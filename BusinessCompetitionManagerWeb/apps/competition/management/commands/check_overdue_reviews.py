"""审批超时催办（2026-11）：扫描各比赛里超时未处理的修改申请/补录审核。

用法：
    python manage.py check_overdue_reviews                 # 全部比赛
    python manage.py check_overdue_reviews --competition 49
可挂系统计划任务按小时执行；已催办过的单据不会重复提醒。
"""

from django.core.management.base import BaseCommand

from apps.common import context as ctx
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db


class Command(BaseCommand):
    help = '检查超过 24 小时未处理的合同修改申请 / 补录审核，并催办超管与申请方'

    def add_arguments(self, parser):
        parser.add_argument('--competition', type=int, default=0,
                            help='只检查指定比赛 ID（默认全部）')
        parser.add_argument('--dry-run', action='store_true',
                            help='只统计不发送催办（默认会真的发消息）')

    def handle(self, *args, **options):
        competition_id = options.get('competition') or 0
        dry_run = bool(options.get('dry_run'))
        competitions = Competition.objects.using('default').all()
        if competition_id:
            competitions = competitions.filter(pk=competition_id)

        total_checked = total_notified = 0
        for competition in competitions:
            if not competition.db_name:
                continue
            try:
                register_competition_db(competition.db_name)
                ctx.set_competition_context(competition.id, competition.db_name)
                pending = Contract.objects.filter(status__in=engine.OVERDUE_STATUSES,
                                                  deleted_at__isnull=True)
                checked = 0
                notified = 0
                for contract in pending:
                    checked += 1
                    if dry_run:
                        if engine.is_overdue(contract):
                            notified += 1
                        continue
                    notified += engine.notify_overdue(contract)
                total_checked += checked
                total_notified += notified
                if checked:
                    self.stdout.write(
                        f'比赛 {competition.id}: 待审批 {checked}，发出催办 {notified}')
            except Exception as exc:  # noqa: BLE001 —— 单库异常不影响其他比赛
                self.stderr.write(f'比赛 {competition.id}: 跳过（{type(exc).__name__}: {exc}）')
            finally:
                ctx.clear_request_context()

        self.stdout.write(self.style.SUCCESS(
            f'完成：检查 {total_checked} 张待审批合同，发出 {total_notified} 条催办'))
