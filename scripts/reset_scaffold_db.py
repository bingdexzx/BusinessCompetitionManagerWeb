"""一次性脚手架清库脚本：备份旧表 → 重置 schema（重构 D7：历史数据不迁移）。"""
import json
import os

from dotenv import load_dotenv

load_dotenv('.env')
import psycopg2  # noqa: E402

conn = psycopg2.connect(
    dbname=os.getenv('DATABASES_NAME'),
    user=os.getenv('DATABASES_USER'),
    password=os.getenv('DATABASES_PASSWORD'),
    host=os.getenv('DATABASES_HOST'),
    port=os.getenv('DATABASES_PORT'),
)
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
tables = [r[0] for r in cur.fetchall()]
print('old tables:', tables)

backup = {}
for t in tables:
    cur.execute('SELECT * FROM "' + t + '"')
    cols = [d[0] for d in cur.description]
    backup[t] = {'columns': cols, 'rows': [[str(v) for v in row] for row in cur.fetchall()]}

os.makedirs('backup', exist_ok=True)
with open('backup/pre-refactor-db-backup.json', 'w', encoding='utf-8') as f:
    json.dump(backup, f, ensure_ascii=False, indent=1)
print('rows backed up:', {k: len(v['rows']) for k, v in backup.items()})

cur.execute('DROP SCHEMA public CASCADE')
cur.execute('CREATE SCHEMA public')
conn.commit()
print('schema reset done')
