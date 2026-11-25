"""慢请求报表：按接口聚合 P50/P95/最大耗时（数据来自网络日志的 duration_ms）。

用法：
    python manage.py report_slow_requests --hours 24 --top 20
    python manage.py report_slow_requests --hours 6 --min-ms 200 --top 50

说明：每个 API 请求都由中间件记录 duration_ms（含 DB 与序列化耗时），
不依赖 pg_stat_statements；需要 SQL 级细节时再开 `log_min_duration_statement=500ms`。
"""

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = '按接口聚合慢请求（网络日志 duration_ms）'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=24, help='统计窗口（小时）')
        parser.add_argument('--top', type=int, default=20, help='输出条数')
        parser.add_argument('--min-ms', type=int, default=0, help='只看 P95 超过该值的接口')

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            self.stdout.write('仅支持 PostgreSQL')
            return

        hours = max(1, options['hours'])
        top = max(1, min(options['top'], 100))
        min_ms = max(0, options['min_ms'])

        sql = """
            SELECT path,
                   count(*) AS n,
                   round(avg(duration_ms)) AS avg_ms,
                   round(percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms)) AS p50,
                   round(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)) AS p95,
                   max(duration_ms) AS max_ms,
                   sum(CASE WHEN status >= 500 THEN 1 ELSE 0 END) AS errors
            FROM logs_networklog
            WHERE occurred_at >= now() - (%s || ' hours')::interval
              AND duration_ms IS NOT NULL
              AND path NOT LIKE '/api/health%%'
            GROUP BY path
            HAVING count(*) >= 3
            ORDER BY p95 DESC NULLS LAST
            LIMIT %s
        """
        with connection.cursor() as cur:
            cur.execute(sql, [hours, top])
            rows = cur.fetchall()

        if not rows:
            self.stdout.write('窗口内没有足够的请求样本')
            return

        rows = [row for row in rows if (row[4] or 0) >= min_ms]

        self.stdout.write(f'== 最近 {hours} 小时慢请求（按 P95 排序，前 {len(rows)} 条） ==')
        self.stdout.write(
            f'{"接口":<58}{"次数":>7}{"avg":>8}{"P50":>8}{"P95":>8}{"max":>9}{"5xx":>6}')
        for path, n, avg_ms, p50, p95, max_ms, errors in rows:
            self.stdout.write(
                f'{path[:56]:<58}{n:>7}{avg_ms or 0:>8}{p50 or 0:>8}'
                f'{p95 or 0:>8}{max_ms or 0:>9}{errors:>6}')

        self.stdout.write(
            '提示：P95 高的接口优先看 SQL 条数与慢查询；'
            '需要 SQL 级明细可临时开 log_min_duration_statement=500ms')
