"""公司 API（§12：GET .../companies/{id}/tables/{entity|finance}、字段手工修改）。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_act_for_company, user_company_ids
from apps.competition.companies.models import Company
from apps.competition.contracts.engine import ContractError, assert_field_writable
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.industries.models import CompanyFieldValue, IndustryField


def _company_data(c: Company) -> dict:
    return {
        'id': c.id, 'name': c.name, 'industryKey': c.industry_key,
        'teamId': c.team_id, 'regionId': c.region_id, 'status': c.status,
    }


class CompanyListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        ids = user_company_ids(request.user)
        qs = Company.objects.all()
        if '*' not in ids:
            qs = qs.filter(pk__in=ids or [-1])
        return Response([_company_data(c) for c in qs])


class CompanyTableView(APIView):
    """实体信息表 / 财务报表（§6.3：按字段定义的 dataTable 归属展开）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk, table):
        if not can_act_for_company(request.user, pk):
            return Response({'code': 403, 'message': '无权查看该公司', 'details': ''}, status=403)
        company = Company.objects.get(pk=pk)
        data_table = 'FINANCE' if table == 'finance' else 'ENTITY'
        fields = IndustryField.objects.filter(data_table=data_table).order_by('id')
        rows = {}
        for row in CompanyFieldValue.objects.filter(company=company, field_key__in=[f.field_key for f in fields]):
            rows.setdefault(row.field_key, {})[row.fiscal_year_id] = row.value
        return Response({
            'company': _company_data(company),
            'table': table,
            'fields': [
                {
                    'key': f.field_key, 'name': f.name, 'type': f.field_type,
                    'isCalculated': f.is_calculated, 'formula': f.formula,
                    'values': rows.get(f.field_key, {}),
                }
                for f in fields
            ],
        })


class CompanyFieldUpdateView(APIView):
    """手工修改字段值（§14.2 source=MANUAL）；被冻结字段拒绝（§7.4）。"""

    permission_classes = [IsAuthenticated]

    def patch(self, request, cid, pk):
        if not can_act_for_company(request.user, pk):
            return Response({'code': 403, 'message': '无权修改该公司', 'details': ''}, status=403)
        company = Company.objects.get(pk=pk)
        field_key = request.data.get('fieldKey') or ''
        value = request.data.get('value')
        fiscal_year_id = request.data.get('fiscalYearId')
        try:
            assert_field_writable(company.id, field_key)
        except ContractError as exc:
            return Response({'code': 400, 'message': str(exc), 'details': ''}, status=400)

        row, created = CompanyFieldValue.objects.get_or_create(
            company=company, field_key=field_key,
            fiscal_year_id=fiscal_year_id or None,
            defaults={'value': value, 'version': 1},
        )
        before = None if created else row.value
        if not created:
            row.value = value
            row.version += 1
            row.save(update_fields=['value', 'version', 'updated_at'])
        definition = IndustryField.objects.filter(field_key=field_key).first()
        snapshot = request.META.get('HTTP_X_DEVICE_SCREEN', '')
        FieldLog.objects.create(
            company=company, field_key=field_key,
            data_table=definition.data_table if definition else '',
            event=FieldLog.Event.VALUE_CHANGE, op='SET',
            before_raw=before, after_raw=value,
            source=FieldLog.Source.MANUAL,
            operator_id=request.user.id, operator_username=request.user.username,
            device_snapshot={'screen': snapshot},
        )
        return Response({'fieldKey': field_key, 'value': value, 'version': row.version})
