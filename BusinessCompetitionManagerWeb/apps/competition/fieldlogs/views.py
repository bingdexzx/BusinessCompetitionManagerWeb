"""字段日志 API（§12：GET .../logs/fields，按用户/设备/公司/字段/时间段/来源检索）。

权限（§15.2）：比赛超管可见本比赛全部；管理员见所辖公司；参赛代表见本队公司。
只增不删（决策 D20）：无修改/删除接口。
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import user_company_ids
from apps.competition.fieldlogs.models import FieldLog


class FieldLogListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        ids = user_company_ids(request.user)
        qs = FieldLog.objects.select_related('company', 'contract').all()
        if '*' not in ids:
            qs = qs.filter(company_id__in=ids or [-1])

        params = request.query_params
        if params.get('companyId'):
            qs = qs.filter(company_id=params['companyId'])
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
    """导出字段日志（比赛超管；导出动作本身入网络日志，§14.3）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        ids = user_company_ids(request.user)
        qs = FieldLog.objects.select_related('company').all()
        if '*' not in ids:
            qs = qs.filter(company_id__in=ids or [-1])
        log_ids = request.data.get('ids') or []
        if log_ids:
            qs = qs.filter(pk__in=log_ids[:1000])
        else:
            qs = qs.order_by('-occurred_at')[:1000]
        return Response({'items': [
            {
                'id': r.id, 'companyName': r.company.name if r.company else None,
                'fieldKey': r.field_key, 'event': r.event, 'op': r.op,
                'before': r.before_raw, 'after': r.after_raw, 'source': r.source,
                'operatorUsername': r.operator_username,
                'occurredAt': r.occurred_at.isoformat(),
            }
            for r in qs
        ]})
