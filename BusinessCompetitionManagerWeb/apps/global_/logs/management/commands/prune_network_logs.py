"""清理网络日志（§14.5 留存策略）：按天 + 按条数双上限，分批删除避免长锁。

用法：
    python manage.py prune_network_logs --days 30 --keep 200000
    python manage.py prune_network_logs --dry-run
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = '按留存策略清理网络日志（默认保留 30 天 / 最近 20 万条）'

    def add_arguments(self, parser):
        from django.conf import settings

        parser.add_argument('--days', type=int,
                            default=settings.NETWORK_LOG_RETENTION_DAYS,
                            help='保留最近 N 天（0 = 不限）')
        parser.add_argument('--keep', type=int,
                            default=settings.NETWORK_LOG_KEEP_ROWS,
                            help='最多保留 N 条（0 = 不限）')
        parser.add_argument('--batch', type=int, default=5000, help='每批删除条数')
        parser.add_argument('--dry-run', action='store_true', help='只统计不删除')

    def handle(self, *args, **options):
        from apps.global_.logs.models import NetworkLog

        days = max(0, options['days'])
        keep = max(0, options['keep'])
        batch = max(100, options['batch'])
        dry_run = options['dry_run']

        total = NetworkLog.objects.count()
        deleted = 0

        if days:
            cutoff = timezone.now() - timedelta(days=days)
            old_qs = NetworkLog.objects.filter(occurred_at__lt=cutoff)
            count = old_qs.count()
            self.stdout.write(f'[{days} 天前] 待删 {count} 条（当前共 {total} 条）')
            if not dry_run:
                deleted += self._delete_batches(old_qs, batch)

        if keep and NetworkLog.objects.count() > keep:
            extra = NetworkLog.objects.count() - keep
            self.stdout.write(f'[条数上限 {keep}] 超出 {extra} 条，从最旧开始删')
            if not dry_run:
                ids = list(
                    NetworkLog.objects.order_by('occurred_at')
                    .values_list('pk', flat=True)[:extra])
                for start in range(0, len(ids), batch):
                    chunk = ids[start:start + batch]
                    NetworkLog.objects.filter(pk__in=chunk).delete()
                    deleted += len(chunk)
                    self.stdout.write(f'  已删除 {deleted} 条')

        remaining = NetworkLog.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'完成：删除 {deleted if not dry_run else 0} 条，剩余 {remaining} 条'))
        if deleted and not dry_run:
            self.stdout.write('建议在低峰期执行 VACUUM (ANALYZE) logs_networklog 回收空间')
            if connection.vendor == 'postgresql':
                self.stdout.write('  psql -c "VACUUM (ANALYZE) logs_networklog"')

    @staticmethod
    def _delete_batches(qs, batch: int) -> int:
        deleted = 0
        while True:
            ids = list(qs.order_by('pk').values_list('pk', flat=True)[:batch])
            if not ids:
                break
            qs.model.objects.filter(pk__in=ids).delete()
            deleted += len(ids)
        return deleted
