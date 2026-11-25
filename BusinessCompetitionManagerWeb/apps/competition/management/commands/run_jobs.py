"""后台任务 worker：把待执行任务跑掉（可挂计划任务，常驻用 --watch）。"""

import time

from django.core.management.base import BaseCommand

from apps.global_.jobs import services as job_services


class Command(BaseCommand):
    help = '执行后台任务队列（结算 / 财年开启结束）'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=5, help='单次最多执行多少个任务')
        parser.add_argument('--watch', action='store_true', help='常驻循环（间隔 --interval 秒）')
        parser.add_argument('--interval', type=float, default=3.0, help='常驻模式的轮询间隔')

    def handle(self, *args, **options):
        limit = max(int(options.get('limit') or 1), 1)
        watch = bool(options.get('watch'))
        interval = max(float(options.get('interval') or 3.0), 0.5)

        while True:
            jobs = job_services.run_pending(limit=limit)
            for job in jobs:
                state = job.get_status_display()
                detail = job.error or job.result
                self.stdout.write(f'{job.kind}#{job.id} {state} {detail}')
            if jobs:
                self.stdout.write(self.style.SUCCESS(f'本轮执行 {len(jobs)} 个任务'))
            elif not watch:
                self.stdout.write('没有待执行任务')
            if not watch:
                return
            time.sleep(interval)
