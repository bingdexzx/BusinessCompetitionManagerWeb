"""公司 API（§12：GET .../companies/{id}/tables/{entity|finance}、字段手工修改）。"""

from django.conf import settings

from django.db import IntegrityError
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
from apps.global_.memberships.models import CompetitionMembership


def _company_data(c: Company, team_name: str = '') -> dict:
    return {
        'id': c.id, 'name': c.name, 'industryKey': c.industry_key,
        'teamId': c.team_id, 'teamName': team_name or '',
        'regionId': c.region_id,
        'status': c.status,
        'createdAt': c.created_at.isoformat(),
    }


def _team_names(team_ids) -> dict:
    """队伍 ID → 队伍名（队伍在全局库；只取这些 ID）。"""
    ids = [t for t in team_ids if t]
    if not ids:
        return {}
    from apps.global_.teams.models import Team
    return dict(Team.objects.filter(pk__in=ids).values_list('id', 'name'))


class CompanyListView(APIView):
    """GET 公司列表（超级管理员/管理员/参赛代表各自按其可见范围过滤）。

    ``?assigned=1``：只要已分配公司（组队完成后由分配流程创建，team_id 非空）——
    「公司管理」页用它，保证未分配公司的行不出现。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        ids = user_company_ids(request.user)
        assigned = (request.query_params.get('assigned') or '').lower() in ('1', 'true', 'yes')
        # ?all=1：创建合同时，管理员（主席团）/超级管理员可选全部公司
        all_requested = (request.query_params.get('all') or '').lower() in ('1', 'true', 'yes')
        if all_requested:
            is_chair = CompetitionMembership.objects.filter(
                user=request.user, competition_id=cid,
                identity=CompetitionMembership.Identity.ADMIN).exists()
            if not (request.user.is_superuser or is_chair):
                return Response(
                    {'code': 403, 'message': '无权查看全部公司', 'details': ''}, status=403)
            ids = {'*'}

        # 公司列表读多写少：按「可见范围 + assigned」缓存 15s；变更由 companies/teams 广播失效
        from apps.common.cache import remember

        scope = '*' if '*' in ids else tuple(sorted(int(c) for c in ids))
        return Response(remember(
            'company-list', (cid, assigned, scope),
            lambda: _company_list(cid, ids, assigned), timeout=settings.CACHE_TTL_COMPANY_LIST))


def _company_list(cid, ids, assigned: bool) -> list:
    qs = Company.objects.all()
    if assigned:
        qs = qs.filter(team_id__isnull=False)
    if '*' not in ids:
        qs = qs.filter(pk__in=ids or [-1])
    rows = list(qs)
    names = _team_names([c.team_id for c in rows])
    return [_company_data(c, names.get(c.team_id, '')) for c in rows]


class CompanyTableView(APIView):
    """实体信息表 / 财务报表（§6.3：按字段定义的 dataTable 归属展开）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk, table):
        # 只读：队长与队员都能看本公司（2026-10 决策：队员只读、操作仅队长）
        if not can_view_company(request.user, pk):
            return Response({'code': 403, 'message': '无权查看该公司', 'details': ''}, status=403)
        company = Company.objects.get(pk=pk)
        from apps.competition.industries.views import active_fields

        data_table = 'FINANCE' if table == 'finance' else 'ENTITY'
        fields = active_fields(IndustryField.objects.filter(data_table=data_table))
        rows, versions = {}, {}
        for row in CompanyFieldValue.objects.filter(
                company=company, field_key__in=[f.field_key for f in fields]):
            rows.setdefault(row.field_key, {})[row.fiscal_year_id] = row.value
            versions.setdefault(row.field_key, {})[row.fiscal_year_id] = row.version
        return Response({
            'company': _company_data(company),
            'table': table,
            'fields': [
                {
                    'key': f.field_key, 'name': f.name, 'type': f.field_type,
                    'isCalculated': f.is_calculated, 'formula': f.formula,
                    'group': (f.meta or {}).get('group', '') if isinstance(f.meta, dict) else '',
                    'min': (f.meta or {}).get('min') if isinstance(f.meta, dict) else None,
                    'max': (f.meta or {}).get('max') if isinstance(f.meta, dict) else None,
                    'values': rows.get(f.field_key, {}),
                    'versions': versions.get(f.field_key, {}),
                }
                for f in fields
            ],
        })


def _coerce_field_value(definition, raw):
    """按字段类型校验并转换手工输入；返回 (value, error)。"""
    field_type = (definition.field_type or '').upper()
    meta = definition.meta if isinstance(definition.meta, dict) else {}
    try:
        if field_type == IndustryField.FieldType.NUMBER:
            value = float(raw)
        elif field_type == IndustryField.FieldType.BOOL:
            if isinstance(raw, bool):
                value = raw
            else:
                text = str(raw).strip().lower()
                if text not in ('true', 'false', '1', '0'):
                    return None, '布尔字段只接受 true / false'
                value = text in ('true', '1')
        elif field_type == IndustryField.FieldType.DATE:
            from datetime import date
            value = raw if isinstance(raw, str) else str(raw)
            date.fromisoformat(value)
        elif field_type == IndustryField.FieldType.TEXT:
            value = str(raw)
        else:
            value = raw
    except (TypeError, ValueError):
        label = definition.name or definition.field_key
        return None, f'「{label}」的值格式不正确（{field_type}）'

    if field_type == IndustryField.FieldType.NUMBER:
        for bound, label, flag in ((meta.get('min'), '最小值', False),
                                   (meta.get('max'), '最大值', True)):
            if bound is None:
                continue
            try:
                limit = float(bound)
            except (TypeError, ValueError):
                continue
            if (value > limit) if flag else (value < limit):
                return None, f'{definition.name or definition.field_key} {flag and "超过" or "低于"}{label} {bound}'
    return value, ''


class CompanyFieldUpdateView(APIView):
    """手工修改字段值（§14.2 source=MANUAL）；被冻结字段拒绝（§7.4）。"""

    permission_classes = [IsAuthenticated]

    def patch(self, request, cid, pk):
        if not can_act_for_company(request.user, pk):
            return Response({'code': 403, 'message': '无权修改该公司', 'details': ''}, status=403)
        company = Company.objects.get(pk=pk)
        field_key = request.data.get('fieldKey') or ''
        raw_value = request.data.get('value')
        fiscal_year_id = request.data.get('fiscalYearId')
        expected_version = request.data.get('expectedVersion')
        # 手工修改视为「填值」：空值 / 空白文本一律拒绝（布尔 false 与数值 0 是合法值）
        if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
            return Response({'code': 400, 'message': '字段值必填', 'details': ''}, status=400)

        definition = IndustryField.objects.filter(field_key=field_key).first()
        if definition is None:
            return Response({'code': 400, 'message': f'字段 {field_key} 未定义',
                             'details': ''}, status=400)
        # 公式字段只由重算写：手工改会被下一次重算覆盖，直接拒绝
        if definition.is_calculated:
            return Response({'code': 400, 'message': '公式计算字段不能手工修改',
                             'details': ''}, status=400)
        value, type_error = _coerce_field_value(definition, raw_value)
        if type_error:
            return Response({'code': 400, 'message': type_error, 'details': ''}, status=400)

        try:
            assert_field_writable(company.id, field_key)
        except ContractError as exc:
            return Response({'code': 400, 'message': str(exc), 'details': ''}, status=400)

        row = CompanyFieldValue.objects.filter(
            company=company, field_key=field_key, fiscal_year_id=fiscal_year_id or None,
        ).first()
        before = row.value if row is not None else None
        if row is None:
            # 首次填值：直接建行（并发建行由唯一约束 + 409 兜底）
            try:
                row = CompanyFieldValue.objects.create(
                    company=company, field_key=field_key,
                    fiscal_year_id=fiscal_year_id or None,
                    value=value, version=1,
                )
            except IntegrityError:
                return Response(
                    {'code': 409, 'message': '该字段已被他人修改，请刷新后重试',
                     'details': ''}, status=409)
        else:
            if expected_version is not None:
                try:
                    expected = int(expected_version)
                except (TypeError, ValueError):
                    return Response({'code': 400, 'message': 'expectedVersion 非法',
                                     'details': ''}, status=400)
                if row.version != expected:
                    return Response(
                        {'code': 409, 'message': '该字段已被他人修改，请刷新后重试',
                         'details': ''}, status=409)
            # 乐观锁 CAS：version 作为条件，被并发改过就 409（而不是静默覆盖）
            updated = CompanyFieldValue.objects.filter(
                pk=row.pk, version=row.version,
            ).update(value=value, version=row.version + 1)
            if not updated:
                return Response(
                    {'code': 409, 'message': '该字段已被他人修改，请刷新后重试',
                     'details': ''}, status=409)
            row.refresh_from_db()
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
        # 手工改了基础字段 → 立刻重算依赖它的公式字段（不等下一次落账/财年）
        from apps.competition.industries.services import recompute_company_fields
        recompute_company_fields(
            company, fiscal_year=row.fiscal_year, operator=request.user,
            log_source=FieldLog.Source.CALC)
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

        from apps.competition.industries.views import active_fields

        qs = IndustryField.objects.all()
        if company.industry_key:
            scoped = qs.filter(plugin_key=company.industry_key)
            if scoped.exists():
                qs = scoped
        # active_fields 返回已按展示顺序排好的列表（不再支持链式 order_by）
        rows = active_fields(qs)
        return Response([
            {'id': f.id, 'key': f.field_key, 'name': f.name, 'fieldType': f.field_type}
            for f in rows
        ])


class CompanyRegionView(APIView):
    """PATCH /api/competitions/{cid}/companies/{pk}/region：指派 / 调整公司所属区域。

    写权限 = can_manage_competition；``{regionId}`` 为空表示清除区域归属；
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
