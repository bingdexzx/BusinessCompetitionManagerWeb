"""比赛库供给（§5.2「建库即迁移」、§9.2 导入编排第一步）。

- ``CREATE DATABASE comp_<id>``（同服务器，PostgreSQL）；
- 对该 alias 执行 ``migrate``：只有比赛域应用的表会被建到比赛库；
- ``ensure_competition_db``：进程内动态注册 alias（幂等）。
"""

from django.conf import settings
from django.core.management import call_command

from apps.competition.routing import COMPETITION_APPS  # noqa: F401  (文档对齐)
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import (  # noqa: F401
    COMPETITION_DB_PREFIX,
    competition_db_name,
    register_competition_db,
)


def ensure_competition_db(db_name: str) -> str:
    """确保比赛库 alias 已注册（不建库、不迁移），返回 alias。"""
    return register_competition_db(db_name)


def database_exists(db_name: str) -> bool:
    import psycopg2

    cfg = settings.DATABASES['default']
    conn = psycopg2.connect(
        dbname='postgres', user=cfg['USER'], password=cfg['PASSWORD'],
        host=cfg['HOST'] or 'localhost', port=cfg['PORT'] or '5432',
    )
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (db_name,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def raw_create_database(db_name: str):
    """CREATE DATABASE（必须在事务外执行，故用裸连接）。"""
    import psycopg2
    from psycopg2 import sql

    cfg = settings.DATABASES['default']
    conn = psycopg2.connect(
        dbname='postgres', user=cfg['USER'], password=cfg['PASSWORD'],
        host=cfg['HOST'] or 'localhost', port=cfg['PORT'] or '5432',
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(db_name)))
    finally:
        conn.close()


def migrate_competition_db(db_name: str):
    """对比赛库执行 migrate（由路由器保证只有比赛域表落地）。"""
    alias = register_competition_db(db_name)
    call_command('migrate', database=alias, verbosity=0, interactive=False)


def create_competition_database(db_name: str) -> str:
    """建库 + 迁移全套比赛域表（决策 D1）。幂等：已存在则只补迁移。"""
    if not database_exists(db_name):
        raw_create_database(db_name)
    migrate_competition_db(db_name)
    return db_name


def provision_all_competitions() -> list:
    """为所有元数据已存在但库未建的比赛补建库（管理命令 / 启动自检用）。"""
    done = []
    for competition in Competition.objects.all().order_by('id'):
        if competition.db_name:
            create_competition_database(competition.db_name)
            done.append(competition.db_name)
    return done
