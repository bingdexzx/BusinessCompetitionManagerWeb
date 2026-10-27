"""资源变更广播（2026-10 决策：实时广播 + 断线 seq 重放）。

写接口成功后落 BroadcastEvent（seq 单调递增）并推送 ``comp_<cid>`` 分组（**推送只当信号**，
不带业务数据）；断线带 ``lastSeq`` 由 ``events_since`` 补发遗漏后自行增量重拉。失败静默。"""

from __future__ import annotations

import logging

logger = logging.getLogger('gipfel.broadcast')

# 系统级（无比赛上下文）事件分组：所有已登录 WS 连接默认订阅，用于全局库资源实时同步。
GLOBAL_GROUP = 'global'


def group_for(competition_id) -> str:
    return f'comp_{int(competition_id)}' if competition_id else GLOBAL_GROUP


def emit_resource_changed(competition_id, resource: str, action: str, payload: dict | None = None):
    """记录并广播一次资源变更；返回 seq（落库失败返回 None，不抛错）。

    **落库（重放源）优先**：写完流水即返回 seq，实时推送尽力而为。``competition_id`` 为空 =
    全局库资源 → 投 ``global`` 分组，否则投 ``comp_<cid>``。
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
    """断线重放：返回作用域内 seq > last_seq 的事件（升序，截断到 limit 条）。

    ``competition_id`` 为空 → 只补发系统级事件（``competition_id IS NULL``）；否则只补该比赛（不串台）。
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
