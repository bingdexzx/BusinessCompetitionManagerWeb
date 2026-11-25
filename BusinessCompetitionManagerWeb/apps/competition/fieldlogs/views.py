"""字段日志 API（§12：GET .../logs/fields，按用户/设备/公司/字段/时间段/来源检索）。

权限（2026-11）：**仅系统超级管理员 / 比赛超级管理员**可见——字段级流水会暴露其他公司的成本、
利润等敏感数据，参赛代表（含队长）一律不可见。只增不删（决策 D20）。
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.capabilities import has_capability
from apps.competition.companies.models import Company
from apps.competition.fieldlogs.models import FieldLog


def _parse_company_id(raw):
    """公司 ID 解析：非法值返回 None（调用方按 400 处理）。"""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class FieldLogCompanyOptionsView(APIView):
    """字段日志的「公司」筛选项：只列**本比赛**有字段日志的公司。

    比赛库隔离：FieldLog/Company 都路由到当前比赛的 ``comp_<id>`` 库，
    因此下拉里不可能出现其他比赛的公司（含比赛包导入产生的非参赛公司）。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not has_capability(request.user, 'view.fieldlogs', cid):
            return Response({'code': 403, 'message': '当前角色没有字段日志查看权限', 'details': ''},
                            status=403)
        rows = (FieldLog.objects
                .filter(company__isnull=False)
                .values('company_id', 'company__name')
                .distinct()
                .order_by('company__name'))
        return Response([
            {'id': r['company_id'],
             'name': r['company__name'] or f"公司 #{r['company_id']}"}
            for r in rows
        ])


class FieldLogListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not has_capability(request.user, 'view.fieldlogs', cid):
            return Response({'code': 403, 'message': '当前角色没有字段日志查看权限', 'details': ''},
                            status=403)
        qs = FieldLog.objects.select_related('company', 'contract', 'region').all()

        params = request.query_params
        if params.get('companyId'):
            company_id = _parse_company_id(params['companyId'])
            if company_id is None:
                return Response({'code': 400, 'message': '公司 ID 非法', 'details': ''},
                                status=400)
            if not Company.objects.filter(pk=company_id).exists():
                return Response({'code': 400, 'message': '公司不属于本比赛', 'details': ''},
                                status=400)
            qs = qs.filter(company_id=company_id)
        if params.get('fieldKey'):
            qs = qs.filter(field_key=params['fieldKey'])
        if params.get('contractId'):
            qs = qs.filter(contract_id=params['contractId'])
        if params.get('operatorId'):
            qs = qs.filter(operator_id=params['operatorId'])
        if params.get('source'):
            qs = qs.filter(source=params['source'])
        if params.get('event'):
            qs = qs.filter(event=params['event'])
        if params.get('traceId'):
            qs = qs.filter(trace_id=params['traceId'])
        if params.get('from'):
            qs = qs.filter(occurred_at__gte=params['from'])
        if params.get('to'):
            qs = qs.filter(occurred_at__lte=params['to'])

        limit = min(int(params.get('limit', 50) or 50), 200)
        offset = int(params.get('offset', 0) or 0)
        total = qs.count()
        rows = qs.order_by('-occurred_at')[offset:offset + limit]
        return Response({
            'total': total,
            'items': [
                {
                    'id': r.id,
                    'companyId': r.company_id,
                    'companyName': r.company.name if r.company else None,
        'regionId': r.region_id,
        'regionName': r.region.name if r.region_id else None,
                    'fieldKey': r.field_key,
                    'dataTable': r.data_table,
                    'event': r.event,
                    'op': r.op,
                    'before': r.before_raw,
                    'after': r.after_raw,
                    'source': r.source,
                    'sourceLabel': r.get_source_display(),
                    'contractId': r.contract_id,
                    'roundNo': r.round_no,
                    'operatorId': r.operator_id,
                    'operatorUsername': r.operator_username,
                    'deviceSnapshot': r.device_snapshot,
                    'traceId': r.trace_id,
                    'occurredAt': r.occurred_at.isoformat(),
                }
                for r in rows
            ],
        })


class FieldLogExportView(APIView):
    """导出字段日志（仅比赛超级管理员；导出动作本身入网络日志，§14.3）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        if not has_capability(request.user, 'view.fieldlogs', cid):
            return Response({'code': 403, 'message': '当前角色没有字段日志查看权限', 'details': ''},
                            status=403)
        qs = FieldLog.objects.select_related('company', 'region').all()
        log_ids = request.data.get('ids') or []
        if log_ids:
            qs = qs.filter(pk__in=log_ids[:1000])
        else:
            qs = qs.order_by('-occurred_at')[:1000]
        if str(request.data.get('format') or '').lower() == 'xlsx':
            from apps.common.xlsx import xlsx_response

            rows = list(qs)
            return xlsx_response(
                filename='字段日志.xlsx', sheet='字段日志',
                headers=['时间', '公司', '区域', '字段', '事件', '操作', '变更前', '变更后',
                         '来源', '操作人'],
                rows=[[
                    r.occurred_at.strftime('%Y-%m-%d %H:%M:%S'),
                    r.company.name if r.company else '—',
                    r.region.name if r.region_id else '—',
                    r.field_key,
                    r.get_event_display(),
                    r.op,
                    r.before_raw,
                    r.after_raw,
                    r.get_source_display(),
                    r.operator_username or '系统',
                ] for r in rows],
                widths={'时间': 20, '字段': 16, '变更前': 24, '变更后': 24},
            )
        return Response({'items': [
            {
                'id': r.id, 'companyName': r.company.name if r.company else None,
                'regionId': r.region_id,
                'regionName': r.region.name if r.region_id else None,
                'fieldKey': r.field_key, 'event': r.event, 'op': r.op,
                'before': r.before_raw, 'after': r.after_raw, 'source': r.source,
                'operatorUsername': r.operator_username,
                'occurredAt': r.occurred_at.isoformat(),
            }
            for r in qs
        ]})
