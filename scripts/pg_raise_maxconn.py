import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BusinessCompetitionManagerWeb'))
import django  # noqa: E402

django.setup()

import psycopg2  # noqa: E402
from django.conf import settings  # noqa: E402

cfg = settings.DATABASES['default']
conn = psycopg2.connect(dbname='postgres', user=cfg['USER'], password=cfg['PASSWORD'],
                        host=cfg['HOST'], port=cfg['PORT'])
conn.autocommit = True
cur = conn.cursor()
cur.execute('SHOW max_connections')
print('max_connections before:', cur.fetchone()[0])
cur.execute('ALTER SYSTEM SET max_connections = 200')
print('ALTER SYSTEM queued (needs service restart)')
conn.close()
