"""比赛内审计（§6.2 audit_logs）：关键动作留痕（人、时间、对象、详情、traceId）。"""

from apps.common import context as ctx
from apps.competition.audit.models import AuditLog


def log_action(action, *, actor=None, target='', payload=None) -> AuditLog:
    snapshot = ctx.get_device_snapshot() or {}
    return AuditLog.objects.create(
        action=action,
        actor_id=getattr(actor, 'id', None),
        actor_username=getattr(actor, 'username', ''),
        target=str(target)[:200],
        payload={**(payload or {}), 'device': snapshot},
        trace_id=ctx.get_trace_id() or '',
    )
