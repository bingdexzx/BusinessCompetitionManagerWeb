"""清理资源变更广播流水（断线重放源）：按天 + 按条数双上限。

保留窗口只需覆盖「客户端离线时长」：超过窗口的旧事件被裁剪后，客户端重连拿到空重放，
会自行做一次全量刷新，不会丢状态。

用法：
    python manage.py prune_broadcast_events --days 7 --keep 100000
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = '按留存策略清理 BroadcastEvent（默认保留 7 天 / 最近 10 万条）'

    def add_arguments(self, parser):
        from django.conf import settings

        parser.add_argument('--days', type=int,
                            default=settings.BROADCAST_EVENT_RETENTION_DAYS,
                            help='保留最近 N 天（0 = 不限）')
        parser.add_argument('--keep', type=int,
                            default=settings.BROADCAST_EVENT_KEEP_ROWS,
                            help='最多保留 N 条（0 = 不限）')
        parser.add_argument('--batch', type=int, default=5000)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from apps.global_.logs.models import BroadcastEvent

        days = max(0, options['days'])
        keep = max(0, options['keep'])
        batch = max(100, options['batch'])
        dry_run = options['dry_run']

        deleted = 0
        total = BroadcastEvent.objects.count()

        if days:
            cutoff = timezone.now() - timedelta(days=days)
            old_qs = BroadcastEvent.objects.filter(created_at__lt=cutoff)
            count = old_qs.count()
            self.stdout.write(f'[{days} 天前] 待删 {count} 条（当前共 {total} 条）')
            if not dry_run:
                while True:
                    ids = list(old_qs.order_by('pk').values_list('pk', flat=True)[:batch])
                    if not ids:
                        break
                    BroadcastEvent.objects.filter(pk__in=ids).delete()
                    deleted += len(ids)

        if keep and BroadcastEvent.objects.count() > keep:
            extra = BroadcastEvent.objects.count() - keep
            self.stdout.write(f'[条数上限 {keep}] 超出 {extra} 条，从最旧开始删')
            if not dry_run:
                ids = list(
                    BroadcastEvent.objects.order_by('seq')
                    .values_list('pk', flat=True)[:extra])
                for start in range(0, len(ids), batch):
                    chunk = ids[start:start + batch]
                    BroadcastEvent.objects.filter(pk__in=chunk).delete()
                    deleted += len(chunk)

        remaining = BroadcastEvent.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'完成：删除 {deleted} 条，剩余 {remaining} 条'))
