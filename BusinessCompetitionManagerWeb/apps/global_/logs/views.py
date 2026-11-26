"""日志中心 API（§12：GET /api/logs/network、/api/logs/devices、导出）。

权限（§15.2）：查看网络日志 / 设备管理 / 导出日志 仅**系统超级管理员**。
只增不删（决策 D20）：日志无修改/删除接口；导出动作本身也入网络日志。
"""

import base64
import json
from datetime import datetime

from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.devices import localize_snapshot
from apps.common.permissions import IsSystemSuperAdmin
from apps.global_.logs.models import Device, NetworkLog


class NetworkLogListView(APIView):
    permission_classes = [IsSystemSuperAdmin]

    def get(self, request):
        qs = NetworkLog.objects.select_related('user').all()
        params = request.query_params
        if params.get('userId'):
            qs = qs.filter(user_id=params['userId'])
        if params.get('competitionId'):
            qs = qs.filter(competition_id=params['competitionId'])
        if params.get('deviceId'):
            qs = qs.filter(device_id=params['deviceId'])
        if params.get('traceId'):
            qs = qs.filter(trace_id=params['traceId'])
        if params.get('status'):
            qs = qs.filter(status=int(params['status']))
        if params.get('method'):
            qs = qs.filter(method=params['method'].upper())
        if params.get('path'):
            qs = qs.filter(path__icontains=params['path'])
        if params.get('from'):
            qs = qs.filter(occurred_at__gte=params['from'])
        if params.get('to'):
            qs = qs.filter(occurred_at__lte=params['to'])

        limit = min(int(params.get('limit', 50) or 50), 200)
        qs = qs.order_by('-occurred_at', '-id')
        cursor = params.get('cursor') or ''
        if cursor:
            try:
                decoded = base64.urlsafe_b64decode(
                    cursor + '=' * (-len(cursor) % 4)).decode()
                payload = json.loads(decoded)
                cursor_time = datetime.fromisoformat(payload['t'])
                cursor_id = int(payload['id'])
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                return Response(
                    {'code': 400, 'message': 'cursor 非法', 'details': ''}, status=400)
            qs = qs.filter(
                Q(occurred_at__lt=cursor_time)
                | Q(occurred_at=cursor_time, id__lt=cursor_id))
        else:
            offset = int(params.get('offset', 0) or 0)
            if offset:
                qs = qs[offset:]

        rows = list(qs[:limit + 1])
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = ''
        if has_more and rows:
            last = rows[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps(
                {'t': last.occurred_at.isoformat(), 'id': last.id},
                separators=(',', ':')).encode()).decode().rstrip('=')

        return Response({
            'items': [
                {
                    'id': r.id,
                    'traceId': r.trace_id,
                    'occurredAt': r.occurred_at.isoformat(),
                    'method': r.method,
                    'path': r.path,
                    'query': r.query,
                    'status': r.status,
                    'durationMs': r.duration_ms,
                    'ip': r.ip,
                    'userId': r.user_id,
                    'username': r.user.username if r.user else None,
                    'competitionId': r.competition_id,
                    'deviceSnapshot': localize_snapshot(r.device_snapshot),
                    'payloadDigest': r.payload_digest,
                    'responseDigest': r.response_digest,
                }
                for r in rows
            ],
            'hasMore': has_more,
            'nextCursor': next_cursor,
        })


class DeviceListView(APIView):
    """设备管理（仅系统超级管理员，§15.2）。"""

    permission_classes = [IsSystemSuperAdmin]

    def get(self, request):
        qs = Device.objects.select_related('user').all()
        if request.query_params.get('userId'):
            qs = qs.filter(user_id=request.query_params['userId'])
        rows = qs.order_by('-last_login_at')[:200]
        return Response([
            {
                'id': d.id,
                'userId': d.user_id,
                'username': d.user.username,
                'os': d.os,
                'browser': d.browser,
                'screen': d.screen,
                'ip': d.ip,
                'ua': d.ua,
                'firstLoginAt': d.first_login_at.isoformat(),
                'lastLoginAt': d.last_login_at.isoformat(),
            }
            for d in rows
        ])


class NetworkLogExportView(APIView):
    """导出网络日志（仅系统超级管理员；导出动作本身也入日志，§14.3）。M0 返回 JSON 流。"""

    permission_classes = [IsSystemSuperAdmin]

    def post(self, request):
        ids = request.data.get('ids') or []
        qs = NetworkLog.objects.select_related('user').all()
        if ids:
            qs = qs.filter(pk__in=ids[:1000])
        else:
            qs = qs.order_by('-occurred_at')[:1000]
        return Response({'items': [
            {
                'id': r.id, 'traceId': r.trace_id, 'occurredAt': r.occurred_at.isoformat(),
                'method': r.method, 'path': r.path, 'status': r.status,
                'durationMs': r.duration_ms, 'ip': r.ip,
                'username': r.user.username if r.user else None,
                'competitionId': r.competition_id,
                'deviceSnapshot': localize_snapshot(r.device_snapshot),
            }
            for r in qs
        ]})
