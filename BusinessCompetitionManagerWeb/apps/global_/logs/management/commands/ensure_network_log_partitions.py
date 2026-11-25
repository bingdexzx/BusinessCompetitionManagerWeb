"""为网络日志分区表提前创建月度分区（默认当前月 + 未来 3 个月）。

用法（建议每月 1 号由计划任务跑一次，提前建未来分区）：
    python manage.py ensure_network_log_partitions --months 3
    python manage.py ensure_network_log_partitions --months 6 --dry-run

若 DEFAULT 分区里已经有目标月份的旧数据，会先把这些行搬到新分区再 ATTACH，
避免 `CREATE TABLE ... PARTITION OF` 因默认分区有重叠数据而失败。
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import connection


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    return date(year, month, 1)


class Command(BaseCommand):
    help = '为 logs_networklog 创建未来月度分区（默认当前月 + 3 个月）'

    def add_arguments(self, parser):
        parser.add_argument('--months', type=int, default=3, help='向后创建几个月（含当前月）')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            self.stdout.write('非 PostgreSQL，跳过')
            return

        months = max(1, options['months'])
        dry_run = options['dry_run']
        start = _month_start(date.today())

        with connection.cursor() as cur:
            cur.execute("""
                select 1 from pg_partitioned_table
                where partrelid = 'logs_networklog'::regclass
            """)
            if not cur.fetchone():
                self.stdout.write(self.style.ERROR(
                    'logs_networklog 还不是分区表，先执行 migrate logs'))
                return

        created = 0
        for offset in range(months):
            month_start = _add_months(start, offset)
            month_end = _add_months(month_start, 1)
            name = f'logs_networklog_p{month_start:%Y%m}'
            with connection.cursor() as cur:
                cur.execute('select to_regclass(%s)', [name])
                if cur.fetchone()[0]:
                    self.stdout.write(f'  {name} 已存在')
                    continue
                self.stdout.write(
                    f'  创建 {name}：{month_start} ~ {month_end}' + ('（dry-run）' if dry_run else ''))
                if dry_run:
                    continue
                temp = f'{name}_tmp'
                cur.execute(f'DROP TABLE IF EXISTS {temp}')
                cur.execute(f'CREATE TABLE {temp} (LIKE logs_networklog INCLUDING DEFAULTS)')
                # 把 DEFAULT 分区里落在该月的行先搬出来（否则 ATTACH 会因约束重叠失败）
                cur.execute(
                    f'INSERT INTO {temp} SELECT * FROM logs_networklog_default '
                    'WHERE occurred_at >= %s AND occurred_at < %s',
                    [month_start, month_end])
                cur.execute(
                    'DELETE FROM logs_networklog_default '
                    'WHERE occurred_at >= %s AND occurred_at < %s',
                    [month_start, month_end])
                cur.execute(
                    f'ALTER TABLE logs_networklog ATTACH PARTITION {temp} '
                    'FOR VALUES FROM (%s) TO (%s)',
                    [month_start, month_end])
                cur.execute(f'ALTER TABLE {temp} RENAME TO {name}')
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'完成：新建 {created} 个分区（dry-run={dry_run}）'))
