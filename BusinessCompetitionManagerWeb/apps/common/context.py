"""请求级 / 线程级上下文（§5.2：thread-local 比赛上下文，兼容 Channels）。

状态：比赛上下文（competition_id + 比赛库 alias）、traceId（§14.1）、设备快照（§14.4）。"""

from asgiref.local import Local

_state = Local()


def _set(attr, value):
    setattr(_state, attr, value)


def _get(attr, default=None):
    return getattr(_state, attr, default)


def set_competition_context(competition_id, db_alias):
    _set('competition_id', competition_id)
    _set('competition_alias', db_alias)


def get_competition_id():
    return _get('competition_id')


def get_competition_alias():
    return _get('competition_alias')


def set_trace_id(trace_id):
    _set('trace_id', trace_id)


def get_trace_id():
    return _get('trace_id')


def set_device_snapshot(snapshot):
    _set('device_snapshot', snapshot)


def get_device_snapshot():
    return _get('device_snapshot', {})


def clear_request_context():
    for attr in (
        'competition_id', 'competition_alias',
        'trace_id', 'device_snapshot', 'log_user', 'log_extra',
    ):
        if hasattr(_state, attr):
            delattr(_state, attr)


def set_log_user(user):
    """登录/注册等匿名端点在视图内回填本次请求的操作者。"""
    _set('log_user', user)


def get_log_user():
    return _get('log_user')
