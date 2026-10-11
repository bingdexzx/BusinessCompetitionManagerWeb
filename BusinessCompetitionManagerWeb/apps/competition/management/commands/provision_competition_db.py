"""比赛库供给管理命令：建库 + 迁移（决策 D1「建库即迁移」）。"""

from django.core.management.base import BaseCommand

from apps.competition import provisioning


class Command(BaseCommand):
    help = '为指定比赛（或全部比赛）创建/补齐独立数据库：provision_competition_db [db_name]'

    def add_arguments(self, parser):
        parser.add_argument('db_name', nargs='?')

    def handle(self, *args, **options):
        db_name = options.get('db_name')
        if db_name:
            provisioning.create_competition_database(db_name)
            self.stdout.write(self.style.SUCCESS(f'比赛库就绪：{db_name}'))
        else:
            done = provisioning.provision_all_competitions()
            for name in done:
                self.stdout.write(self.style.SUCCESS(f'比赛库就绪：{name}'))
            if not done:
                self.stdout.write('没有待供给的比赛')
