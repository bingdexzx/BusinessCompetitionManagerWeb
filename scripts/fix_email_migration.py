"""邮箱迁移数据清洗：给存量空邮箱行分配唯一占位邮箱（迁移完成后置回 NULL）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BusinessCompetitionManagerWeb'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')

import django  # noqa: E402

django.setup()

import psycopg2  # noqa: E402
from django.conf import settings  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else 'placeholder'

cfg = settings.DATABASES['default']
conn = psycopg2.connect(dbname=cfg['NAME'], user=cfg['USER'], password=cfg['PASSWORD'],
                        host=cfg['HOST'], port=cfg['PORT'])
cur = conn.cursor()
cur.execute('SELECT id, username, email FROM accounts_user')
print('users:', cur.fetchall())

if mode == 'placeholder':
    cur.execute(
        "UPDATE accounts_user SET email = 'placeholder-' || id || '@invalid.local' "
        "WHERE email = '' OR email IS NULL"
    )
    print('placeholder rows:', cur.rowcount)
else:  # clean
    cur.execute("UPDATE accounts_user SET email = NULL WHERE email LIKE 'placeholder-%@invalid.local'")
    print('cleared rows:', cur.rowcount)

conn.commit()
conn.close()
print('done:', mode)
