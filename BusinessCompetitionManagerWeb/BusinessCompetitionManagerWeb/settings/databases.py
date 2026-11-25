"""数据库拓扑：全局库 + 每场比赛独立库（重构方案 §5.2，决策 D1）。

``default`` 全局库（.env 的 DATABASES_NAME，默认 gipfel_global）：账号、学校、比赛元数据、
身份、设备、网络日志等；``comp_<id>`` 比赛库：导入/创建比赛时动态 ``CREATE DATABASE`` +
``migrate``，承载公司/产业字段/合同/财年/字段日志等比赛域数据。"""

import os
import threading

from pathlib import Path

GLOBAL_DB_NAME = os.getenv('DATABASES_NAME', 'gipfel_global')

GLOBAL_DB = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': GLOBAL_DB_NAME,
    'USER': os.getenv('DATABASES_USER', 'postgres'),
    'PASSWORD': os.getenv('DATABASES_PASSWORD', ''),
    'HOST': os.getenv('DATABASES_HOST', 'localhost'),
    'PORT': os.getenv('DATABASES_PORT', '5432'),

    # 连接复用（秒）：实测新建一条 PG 连接 ~44ms、复用后查询 ~0.03ms，**必须复用**。
    # 陷阱：Django 每线程一条连接，CONN_MAX_AGE>0 会让连接随线程数滞留，故 PG
    # max_connections 必须 ≥ 2×并发线程数 + 余量（本机 200），并配合背压限流。
    'CONN_MAX_AGE': int(os.getenv('DATABASES_CONN_MAX_AGE', '60')),
    # 取出连接前先健康探测，避免复用到已被服务端断开的死连接。
    'CONN_HEALTH_CHECKS': True,
    # 走 PgBouncer transaction pooling 时必须禁用服务端游标（Django 官方建议）
    'DISABLE_SERVER_SIDE_CURSORS': os.getenv(
        'DATABASES_DISABLE_SERVER_SIDE_CURSORS', 'false').strip().lower()
        in ('1', 'true', 'yes', 'on'),
    'OPTIONS': {
        # 连接建立超时（秒）：DB 不可用时快速失败，避免请求线程长时间挂起。
        'connect_timeout': int(os.getenv('DATABASES_CONNECT_TIMEOUT', '5')),
        # TCP keepalive：及时发现 NAT / 防火墙静默断开的空闲连接。
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5,
    },
}

DATABASES = {
    'default': GLOBAL_DB,
}

COMPETITION_DB_PREFIX = 'comp_'

DATABASE_ROUTERS = ['apps.competition.routing.CompetitionDatabaseRouter']


def competition_db_name(competition_id: int) -> str:
    """比赛库命名（决策 D1 / §6.1 competitions.dbName）。"""
    return f'{COMPETITION_DB_PREFIX}{competition_id}'


def competition_db_config(db_name: str) -> dict:
    """由全局库连接克隆出比赛库连接配置（同服务器，仅库名不同）。"""
    cfg = dict(GLOBAL_DB)
    cfg['NAME'] = db_name
    return cfg


# 注册锁：并发注册同一 alias 需互斥；settings.DATABASES 是进程内状态，每 worker 各自注册。
_REGISTRY_LOCK = threading.Lock()


def register_competition_db(db_name: str) -> str:
    """把比赛库注册进 settings.DATABASES（幂等），返回 alias（即库名）。

    ``settings.DATABASES`` 是**进程内**状态：多核下每个 worker 各自注册（首次访问该比赛时惰性
    完成）。Django 连接每线程一条，预算见 docs/多核并发与吞吐优化.md。"""
    if not db_name.startswith(COMPETITION_DB_PREFIX):
        raise ValueError(f'非法比赛库名：{db_name!r}')
    with _REGISTRY_LOCK:
        if db_name not in DATABASES:
            DATABASES[db_name] = competition_db_config(db_name)
    return db_name
