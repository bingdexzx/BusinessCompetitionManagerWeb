"""产业字段只读视图（比赛域）：给前端做 key → 中文名 的展示映射。"""

from django.conf import settings

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition, can_read_competition
from apps.competition.industries.models import IndustryField


def _is_active(field) -> bool:
    """字段是否启用：meta.active 缺省视为启用（2026-11 新增，不动表结构）。"""
    meta = field.meta if isinstance(field.meta, dict) else {}
    return meta.get('active', True) is not False


def _order_of(field):
    meta = field.meta if isinstance(field.meta, dict) else {}
    try:
        return int(meta.get('order', 10000))
    except (TypeError, ValueError):
        return 10000


def active_fields(queryset=None):
    """取出启用中的字段（展示顺序：meta.order → id）。"""
    from apps.competition.industries.models import IndustryField

    rows = list(queryset if queryset is not None else IndustryField.objects.all())
    rows = [f for f in rows if _is_active(f)]
    rows.sort(key=lambda f: (_order_of(f), f.id))
    return rows


def _err(code: int, message: str) -> Response:
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


class IndustryFieldListView(APIView):
    """GET /api/competitions/{cid}/industry-fields —— 本比赛全部产业字段元数据。

    前端只用它把 `cash` / `capacity` 这类字段键换成中文名（字段名取自插件 FIELDS[].name）。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not can_read_competition(request.user, cid):
            return _err(403, '仅比赛成员可操作')
        include_inactive = (request.query_params.get('includeInactive') or '').lower() in (
            '1', 'true', 'yes')
        from apps.common.cache import remember

        return Response(remember(
            'industry-fields', (cid, include_inactive),
            lambda: self._build_payload(include_inactive),
            timeout=settings.CACHE_TTL_INDUSTRY_FIELDS))

    @staticmethod
    def _build_payload(include_inactive: bool) -> list:
        rows = list(IndustryField.objects.all())
        rows = [f for f in rows if include_inactive or _is_active(f)]
        rows.sort(key=lambda f: (_order_of(f), f.id))
        return [
            {
                'id': f.id,
                'key': f.field_key,
                'name': f.name or f.field_key,
                'fieldType': f.field_type,
                'dataTable': f.data_table,
                'pluginKey': f.plugin_key,
                'formula': f.formula,
                'isCalculated': f.is_calculated,
                'timerEnabled': f.timer_enabled,
                'group': (f.meta or {}).get('group', '') if isinstance(f.meta, dict) else '',
                'order': _order_of(f),
                'active': _is_active(f),
            }
            for f in rows
        ]


class IndustryFieldGroupView(APIView):
    """PATCH /api/competitions/{cid}/industry-fields/<key>：字段治理（仅系统超级管理员）。

    可改：``group``（展示分组）、``order``（展示顺序）、``active``（启用/停用）。
    全部落在 ``meta`` 上（不动表结构），每次变更记 SCHEMA_CHANGE 字段日志。
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, cid, key):
        if not can_manage_competition(request.user, cid):
            return _err(403, '仅超级管理员可操作')
        field = IndustryField.objects.filter(field_key=key).first()
        if field is None:
            return _err(404, '字段不存在')

        meta = dict(field.meta or {})
        before = {
            'group': meta.get('group', ''),
            'order': meta.get('order'),
            'active': meta.get('active', True),
        }
        changed_ops = []

        if 'group' in request.data:
            group = (request.data.get('group') or '').strip()
            if len(group) > 40:
                return _err(400, '分组名最长 40 个字符')
            meta['group'] = group
            if group != before['group']:
                changed_ops.append('SET_GROUP')

        if 'order' in request.data:
            raw_order = request.data.get('order')
            try:
                order = int(raw_order)
            except (TypeError, ValueError):
                return _err(400, '排序值必须是整数')
            meta['order'] = order
            if order != before['order']:
                changed_ops.append('SET_ORDER')

        if 'active' in request.data:
            active = bool(request.data.get('active'))
            meta['active'] = active
            if active != before['active']:
                changed_ops.append('SET_ACTIVE')

        if not changed_ops:
            return Response({'key': key, 'group': meta.get('group', ''),
                             'order': meta.get('order'), 'active': _is_active(field)})

        field.meta = meta
        field.save(update_fields=['meta'])

        from apps.competition.fieldlogs.models import FieldLog

        FieldLog.objects.create(
            company=None, field_key=key, data_table=field.data_table,
            event=FieldLog.Event.SCHEMA_CHANGE, op='+'.join(changed_ops)[:16],
            before_raw=before,
            after_raw={'group': meta.get('group', ''),
                       'order': meta.get('order'),
                       'active': meta.get('active', True)},
            source=FieldLog.Source.MANUAL,
            operator_id=request.user.id, operator_username=request.user.username,
        )
        return Response({'key': key, 'group': meta.get('group', ''),
                         'order': meta.get('order'), 'active': _is_active(field)})


class IndustryFieldReorderView(APIView):
    """POST /api/competitions/{cid}/industry-fields/reorder：按给定顺序重排字段。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _err(403, '仅超级管理员可操作')
        keys = request.data.get('keys')
        if not isinstance(keys, list) or not keys:
            return _err(400, '请提供字段顺序 keys')
        fields = {f.field_key: f for f in IndustryField.objects.filter(field_key__in=keys)}
        missing = [k for k in keys if k not in fields]
        if missing:
            return _err(400, f'未知字段：{", ".join(missing)}')
        for index, key in enumerate(keys, start=1):
            field = fields[key]
            meta = dict(field.meta or {})
            if meta.get('order') == index:
                continue
            meta['order'] = index
            field.meta = meta
            field.save(update_fields=['meta'])
        return Response({'ok': True, 'count': len(keys)})
