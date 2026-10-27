"""资源变更广播（2026-10 决策：实时广播 + 断线 seq 重放）。

与旧系统 `resource:changed` 等价语义：
- 写接口成功后调用 `emit_resource_changed` 落一条 BroadcastEvent（seq 单调递增），
  并经 PostgreSQL 通道层推送到 `comp_<cid>` 分组（**推送只当信号**，不带业务数据）；
- 客户端断线重连带 `lastSeq`，`events_since` 补发遗漏事件后自行增量重拉。

失败静默不影响业务写入（广播是增强能力）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger('gipfel.broadcast')

# 系统级（无比赛上下文）事件分组：所有已登录 WS 连接默认订阅，用于
# 用户/学校/比赛/插件等全局库资源的实时同步（这类事件的 competition_id 为 None）。
GLOBAL_GROUP = 'global'


def group_for(competition_id) -> str:
    """事件投递分组：有比赛上下文 → ``comp_<cid>``；系统级 → ``global``。"""
    return f'comp_{int(competition_id)}' if competition_id else GLOBAL_GROUP


def emit_resource_changed(competition_id, resource: str, action: str, payload: dict | None = None):
    """记录并广播一次资源变更；返回 seq（落库失败返回 None，不抛错）。

    语义：**落库（重放源）优先**——流水写入成功即返回 seq，实时推送尽力而为
    （推送失败不影响断线重放补发）。

    ``competition_id`` 为空 = 系统级资源（全局库）→ 投递 ``global`` 分组；
    否则投递 ``comp_<cid>`` 分组（仅该比赛成员订阅）。
    """
    try:
        from apps.global_.logs.models import BroadcastEvent

        row = BroadcastEvent.objects.create(
            competition_id=competition_id or None,
            resource=str(resource)[:64],
            action=str(action)[:16],
            payload=payload or {},
        )
    except Exception:  # noqa: BLE001 —— 广播失败不影响业务
        logger.exception('resource:changed 落库失败 resource=%s', resource)
        return None

    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(
                group_for(row.competition_id),
                {
                    'type': 'resource.changed',   # → consumer.resource_changed
                    'seq': row.seq,
                    'resource': row.resource,
                    'action': row.action,
                    'competitionId': row.competition_id,
                    'payload': row.payload,
                    'ts': row.created_at.isoformat(),
                },
            )
    except Exception:  # noqa: BLE001 —— 推送失败可由断线重放兜底
        logger.exception('resource:changed 推送失败 resource=%s（重放可补发）', resource)
    return row.seq


def events_since(competition_id, last_seq: int, limit: int = 200) -> list:
    """断线重放：返回匹配作用域内 seq > last_seq 的事件（升序，截断到 limit 条）。

    ``competition_id`` 为空 → 只补发**系统级**事件（``competition_id IS NULL``），
    与 ``global`` 分组的语义一致；否则只补发该比赛的事件（不串台）。
    """
    from apps.global_.logs.models import BroadcastEvent

    qs = BroadcastEvent.objects.filter(seq__gt=int(last_seq or 0))
    if competition_id:
        qs = qs.filter(competition_id=competition_id)
    else:
        qs = qs.filter(competition_id__isnull=True)
    rows = list(qs.order_by('seq')[: max(1, min(int(limit), 500))])
    return [
        {
            'seq': row.seq, 'resource': row.resource, 'action': row.action,
            'competitionId': row.competition_id, 'payload': row.payload,
            'ts': row.created_at.isoformat(),
        }
        for row in rows
    ]
