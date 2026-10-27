"""数据库拓扑：全局库 + 每场比赛独立库（重构方案 §5.2，决策 D1）。

- ``default`` 全局库（.env 中 DATABASES_NAME，默认 gipfel_global）：账号、学校、
  比赛元数据、比赛内身份、设备、网络日志等全局域数据；
- ``comp_<id>`` 比赛库：导入/创建比赛时动态 ``CREATE DATABASE`` + ``migrate``，
  承载该公司/产业字段/合同/财年/字段日志等比赛域数据。
"""

import os
import threading

from pathlib import Path

# ---------------------------------------------------------------- 全局库连接

GLOBAL_DB_NAME = os.getenv('DATABASES_NAME', 'gipfel_global')

GLOBAL_DB = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': GLOBAL_DB_NAME,
    'USER': os.getenv('DATABASES_USER', 'postgres'),
    'PASSWORD': os.getenv('DATABASES_PASSWORD', ''),
    'HOST': os.getenv('DATABASES_HOST', 'localhost'),
    'PORT': os.getenv('DATABASES_PORT', '5432'),

    # ---- 连接层优化（详见 docs/数据库优化.md）----
    # 连接复用（秒）：实测本机新建一条 PG 连接固定 ~44ms（后端进程启动开销），
    # 复用后查询仅 ~0.03ms——**必须复用**。
    # 前提（实测教训）：Django 每线程一条连接，CONN_MAX_AGE>0 会让连接随线程数滞留，
    # 故 PostgreSQL `max_connections` 必须 ≥ 2×并发线程数 + 余量（本机已调 200，
    # 配合 DB_MAX_CONCURRENT_REQUESTS 背压限流）；上 PgBouncer 后可进一步放宽。
    'CONN_MAX_AGE': int(os.getenv('DATABASES_CONN_MAX_AGE', '60')),
    # 取出连接前先做健康探测，避免复用到已被服务端断开的死连接。
    'CONN_HEALTH_CHECKS': True,
    'OPTIONS': {
        # 连接建立超时（秒）：DB 不可用时快速失败，避免请求线程长时间挂起。
        'connect_timeout': int(os.getenv('DATABASES_CONNECT_TIMEOUT', '5')),
        # TCP keepalive：及时发现 NAT/防火墙静默断开的空闲连接。
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5,
    },
}

DATABASES = {
    'default': GLOBAL_DB,
}

# 比赛库统一前缀（comp_<id>）
COMPETITION_DB_PREFIX = 'comp_'

# 多库路由器：把比赛域模型路由到当前比赛上下文对应的库
DATABASE_ROUTERS = ['apps.competition.routing.CompetitionDatabaseRouter']


def competition_db_name(competition_id: int) -> str:
    """比赛库命名（决策 D1 / §6.1 competitions.dbName）。"""
    return f'{COMPETITION_DB_PREFIX}{competition_id}'


def competition_db_config(db_name: str) -> dict:
    """由全局库连接克隆出比赛库连接配置（同服务器，仅库名不同）。"""
    cfg = dict(GLOBAL_DB)
    cfg['NAME'] = db_name
    return cfg


# 注册锁：多 worker × 多线程下并发注册同一 alias 需互斥（进程内互斥即可，
# 每个 worker 进程各自注册自己那份配置，天然正确）。
_REGISTRY_LOCK = threading.Lock()


def register_competition_db(db_name: str) -> str:
    """把比赛库注册进 settings.DATABASES（幂等），返回 alias（即库名）。

    多进程说明：``settings.DATABASES`` 是**进程内**状态，多核部署下每个 worker
    进程都要各自注册（首次访问该比赛时惰性完成，成本为一次字典赋值）；
    Django 的连接是「每线程一条」，与 worker/线程数成正比，连接预算见
    docs/多核并发与吞吐优化.md。
    """
    if not db_name.startswith(COMPETITION_DB_PREFIX):
        raise ValueError(f'非法比赛库名：{db_name!r}')
    with _REGISTRY_LOCK:
        if db_name not in DATABASES:
            DATABASES[db_name] = competition_db_config(db_name)
    return db_name


def registered_competition_dbs() -> dict:
    """当前进程内已注册的比赛库 {alias: db_name}。"""
    return {
        alias: cfg['NAME']
        for alias, cfg in DATABASES.items()
        if alias.startswith(COMPETITION_DB_PREFIX)
    }
