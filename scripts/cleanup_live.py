"""清理实时联调残留（M1实时联调赛 / live_m1）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BusinessCompetitionManagerWeb'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')

import django  # noqa: E402

django.setup()

import psycopg2  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connections  # noqa: E402

from apps.global_.competitions.models import Competition  # noqa: E402

names = []
for c in Competition.objects.filter(name__contains='联调'):
    names.append(c.db_name)
    c.delete()
get_user_model().objects.filter(username='live_m1').delete()
connections.close_all()

cfg = settings.DATABASES['default']
conn = psycopg2.connect(dbname='postgres', user=cfg['USER'], password=cfg['PASSWORD'],
                        host=cfg['HOST'], port=cfg['PORT'])
conn.autocommit = True
cur = conn.cursor()
for name in names:
    cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    print('已删除联调比赛库:', name)
conn.close()
print('联调残留清理完成')
