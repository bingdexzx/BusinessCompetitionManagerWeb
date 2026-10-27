"""公司 API（§12：GET .../companies/{id}/tables/{entity|finance}、字段手工修改）。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import (
    can_act_for_company, can_manage_competition, can_view_company, user_company_ids,
)
from apps.competition.companies.models import Company
from apps.competition.contracts.engine import ContractError, assert_field_writable
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.competition.regions.models import Region


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
        # 只读：队长与队员都能看本公司（2026-10 决策：队员只读、操作仅队长）
        if not can_view_company(request.user, pk):
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


class CompanyIndustryFieldsView(APIView):
    """GET /api/competitions/{cid}/companies/{pk}/industry-fields：该公司可选的产业字段元数据。

    区域总览「添加数据框」的字段下拉用它（旧系统走产业类型字段接口）：
    优先该公司的产业插件字段；公司没绑产业（或插件字段缺失）时退回全部字段，避免下拉为空。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        if not can_view_company(request.user, pk):
            return Response({'code': 403, 'message': '无权查看该公司', 'details': ''}, status=403)
        company = Company.objects.filter(pk=pk).first()
        if company is None:
            return Response({'code': 404, 'message': '公司不存在', 'details': ''}, status=404)

        qs = IndustryField.objects.all()
        if company.industry_key:
            scoped = qs.filter(plugin_key=company.industry_key)
            if scoped.exists():
                qs = scoped
        return Response([
            {'id': f.id, 'key': f.field_key, 'name': f.name, 'fieldType': f.field_type}
            for f in qs.order_by('id')
        ])


class CompanyRegionView(APIView):
    """PATCH /api/competitions/{cid}/companies/{pk}/region：指派 / 调整公司所属赛区。

    写权限 = can_manage_competition；``{regionId}`` 为空表示清除赛区归属；
    区域不存在返回 400。
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '无权管理本比赛', 'details': ''}, status=403)
        company = Company.objects.filter(pk=pk).first()
        if company is None:
            return Response({'code': 404, 'message': '公司不存在', 'details': ''}, status=404)

        raw = request.data.get('regionId')
        if raw in (None, ''):
            company.region = None
        else:
            try:
                region_id = int(raw)
            except (TypeError, ValueError):
                return Response({'code': 400, 'message': '区域不存在', 'details': ''}, status=400)
            region = Region.objects.filter(pk=region_id).first()
            if region is None:
                return Response({'code': 400, 'message': '区域不存在', 'details': ''}, status=400)
            company.region = region
        company.save(update_fields=['region'])
        return Response(_company_data(company))
