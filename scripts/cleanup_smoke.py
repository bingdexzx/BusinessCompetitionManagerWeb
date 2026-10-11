"""清理冒烟测试残留（仅冒烟数据：名称含「冒烟」的比赛 / smoke_*、m0_*、m1_* 用户 / 冒烟大学 / 游离 comp_* 库）。

注意：仅用于开发环境重置冒烟数据；不会触碰其他比赛与账号。
"""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BusinessCompetitionManagerWeb'))

import django  # noqa: E402

django.setup()

import psycopg2  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

from apps.global_.competitions.models import Competition  # noqa: E402
from apps.global_.schools.models import School  # noqa: E402

User = get_user_model()

smoke = Competition.objects.filter(name__contains='冒烟')
known = {c.db_name for c in Competition.objects.exclude(name__contains='冒烟') if c.db_name}
count = smoke.count()
smoke.delete()
deleted_users, _ = User.objects.filter(
    username__regex=r'^(smoke_|m0_|m1_)'
).delete()
School.objects.filter(name='冒烟大学').delete()

cfg = settings.DATABASES['default']
conn = psycopg2.connect(dbname='postgres', user=cfg['USER'], password=cfg['PASSWORD'],
                        host=cfg['HOST'], port=cfg['PORT'])
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT datname FROM pg_database WHERE datname LIKE 'comp\\_%'")
for (name,) in cur.fetchall():
    if name in known:
        print('保留有效比赛库:', name)
        continue
    cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    print('已删除游离比赛库:', name)
conn.close()
print(f'冒烟残留清理完成：比赛 {count} 个、用户 {deleted_users} 个')
