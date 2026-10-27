"""多库路由器（§5.2，决策 D1）：按线程局部比赛上下文把比赛域模型路由到 comp_<id>。

- 全局域应用 → ``default``（全局库）；
- 比赛域应用 → 当前比赛上下文的库 alias；
- 迁移隔离：全局库只迁移全局域表，比赛库只迁移比赛域表（建库即迁移全套比赛域表）。
"""

from apps.common.context import get_competition_alias

GLOBAL_APPS = {
    'accounts', 'schools', 'competitions', 'memberships', 'logs',
    'teams', 'invites', 'profiles', 'inmail',
    'admin', 'auth', 'contenttypes', 'sessions', 'messages', 'staticfiles',
}

COMPETITION_APPS = {
    'companies', 'industries', 'contracts', 'fiscal', 'ledger',
    'fieldlogs', 'basedata', 'comp_messages', 'comp_audit', 'settlement',
    'stock', 'regions',
}


class CompetitionDatabaseRouter:
    """按 app_label + 比赛上下文路由读写与迁移。"""

    # ------------------------------------------------------------ 读写

    def db_for_read(self, model, **hints):
        return self._route(model)

    def db_for_write(self, model, **hints):
        return self._route(model)

    def _route(self, model):
        app_label = model._meta.app_label
        if app_label in COMPETITION_APPS:
            alias = get_competition_alias()
            if not alias:
                raise RuntimeError(
                    f'比赛域模型 {app_label}.{model.__name__} 的访问必须处于比赛上下文中'
                    '（请求 /api/competitions/{cid}/... 或携带 X-Competition-Id 头）'
                )
            return alias
        return 'default'

    # ------------------------------------------------------------ 迁移

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in COMPETITION_APPS:
            # 比赛域表只建在比赛库（comp_*）
            return db.startswith('comp_')
        if app_label in GLOBAL_APPS:
            return db == 'default'
        # 其余第三方/内建应用只进全局库
        return db == 'default'

    def allow_migrate_model(self, db, model, **hints):
        return self.allow_migrate(db, model._meta.app_label, model._meta.model_name, **hints)

    # ------------------------------------------------------------ 关系

    def allow_relation(self, obj1, obj2, **hints):
        """同库对象才允许外键关系（跨库只存整数 ID，不建外键）。"""
        a1 = obj1._meta.app_label in COMPETITION_APPS
        a2 = obj2._meta.app_label in COMPETITION_APPS
        return a1 == a2
