"""区域 / 消费者需求 / 总览卡片视图（比赛域，路由挂 /api 前缀下）。

权限：读 = 本比赛成员；写 = can_manage_competition（对齐 basedata）。
区域总览（2026-10 需求）：区域在地图管理里创建（MapNode.region），总览页只做展示与卡片配置；
map-overview 的区域 = MapNode.region 去重 ∪ 已有 Region 实体，卡片值由服务端算好；
by-name 接口按区域名存卡片（无 Region 行时自动建）。
"""

from __future__ import annotations

import json

from django.db.models import Count
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition, can_read_competition
from apps.competition.regions import services as region_services
from apps.competition.regions.models import ConsumerDemand, Region

# 公司「所在地」字段键：与地图节点名匹配，决定公司属于哪个区域（旧系统口径）
LOCATION_FIELD_KEY = 'location'


def _err(code: int, message: str) -> Response:
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


def _require_member(user, cid) -> bool:
    """读权限：本比赛成员（系统超级管理员恒通过）——实现在 apps.common.authority。"""
    return can_read_competition(user, cid)


def _region_data(region: Region, demand_count: int | None = None) -> dict:
    return {
        'id': region.id,
        'name': region.name,
        'description': region.description or '',
        'overviewCards': region.overview_cards or [],
        'demandCount': demand_count if demand_count is not None else None,
        'updatedAt': region.updated_at.isoformat(),
    }


def _demand_data(demand: ConsumerDemand) -> dict:
    return {
        'id': demand.id,
        'regionId': demand.region_id,
        'regionName': demand.region.name if demand.region_id else '',
        'productId': demand.product_id,
        'productName': demand.product_name or '',
        'quantity': demand.quantity,
        'note': demand.note or '',
        'updatedAt': demand.updated_at.isoformat(),
    }


def _parse_location_value(raw) -> str:
    """解析 location 字段值：JSON 字符串 '"北京"' → 北京；否则去空格返回。"""
    if raw is None:
        return ''
    text = str(raw)
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        try:
            value = json.loads(text)
            if isinstance(value, str):
                return value
        except (ValueError, TypeError):
            pass
    return text.strip()


def _local_companies(region_name: str) -> list:
    """该区域内的公司：公司 ``location`` 字段值 == 该区域下某个地图节点名（旧系统口径）。"""
    from apps.competition.basedata.models import MapNode
    from apps.competition.industries.models import CompanyFieldValue, IndustryField

    node_names = list(
        MapNode.objects.filter(region=region_name).exclude(name='')
        .values_list('name', flat=True)
    )
    if not node_names:
        return []
    if not IndustryField.objects.filter(field_key=LOCATION_FIELD_KEY).exists():
        return []
    node_set = set(node_names)

    seen, out = set(), []
    rows = (
        CompanyFieldValue.objects
        .filter(field_key=LOCATION_FIELD_KEY)
        .select_related('company')
    )
    for row in rows:
        company = row.company
        if company is None or company.id in seen:
            continue
        if _parse_location_value(row.value) in node_set:
            seen.add(company.id)
            out.append({'id': company.id, 'name': company.name,
                        'industryKey': company.industry_key})
    return out


def _resolve_cards(cards: list) -> list:
    """补全卡片并算好当前值（公司/字段缺失 → valid=False）；取值优先最新财年行，其次无财年行，最后初始值。"""
    from apps.competition.companies.models import Company
    from apps.competition.industries.models import CompanyFieldValue, IndustryField

    cards = [c for c in (cards or []) if isinstance(c, dict)]
    company_ids = {c.get('companyId') for c in cards if c.get('companyId')}
    field_ids = {c.get('industryFieldId') for c in cards if c.get('industryFieldId')}
    companies = {c.id: c for c in Company.objects.filter(pk__in=company_ids)}
    fields = {f.id: f for f in IndustryField.objects.filter(pk__in=field_ids)}

    field_keys = {f.field_key for f in fields.values()}
    best = {}
    if company_ids and field_keys:
        for row in CompanyFieldValue.objects.filter(
                company_id__in=company_ids, field_key__in=field_keys).select_related('fiscal_year'):
            key = (row.company_id, row.field_key)
            current = best.get(key)
            if current is None:
                best[key] = row
                continue
            current_year = current.fiscal_year.year if current.fiscal_year_id else None
            row_year = row.fiscal_year.year if row.fiscal_year_id else None
            if row_year is not None and (current_year is None or row_year > current_year):
                best[key] = row

    out = []
    for card in cards:
        company = companies.get(card.get('companyId'))
        field = fields.get(card.get('industryFieldId'))
        valid = bool(company and field)
        value = None
        if valid:
            row = best.get((company.id, field.field_key))
            value = row.value if row is not None else field.default_value
        out.append({
            'id': card.get('id'),
            'displayName': card.get('displayName'),
            'companyId': card.get('companyId'),
            'industryFieldId': card.get('industryFieldId'),
            'zone': card.get('zone') or 'bottom',
            'value': value,
            'valid': valid,
            'fieldType': field.field_type if field else '',
        })
    return out


def _map_overview() -> list:
    """区域概览聚合：地图节点区域（首次出现顺序）∪ 已有 Region 实体。"""
    from apps.competition.basedata.models import MapNode

    names, seen = [], set()
    for name in (
        MapNode.objects.exclude(region='').order_by('id').values_list('region', flat=True)
    ):
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    region_by_name = {}
    for region in Region.objects.all().order_by('id'):
        region_by_name[region.name] = region
        if region.name not in seen:
            seen.add(region.name)
            names.append(region.name)

    out = []
    for name in names:
        region = region_by_name.get(name)
        out.append({
            'id': region.id if region else None,
            'region': name,
            'companies': _local_companies(name),
            'cards': _resolve_cards(region.overview_cards if region else []),
        })
    return out


class RegionMapOverviewView(APIView):
    """GET /api/competitions/{cid}/regions/map-overview（区域总览页数据源）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _err(403, '仅比赛成员可操作')
        return Response(_map_overview())


class RegionCardsByNameView(APIView):
    """PUT /regions/by-name/<name>/overview-cards（按区域名存卡片）：区域由地图管理创建，无 Region 行时按名建。"""

    permission_classes = [IsAuthenticated]

    def put(self, request, cid, name):
        if not can_manage_competition(request.user, cid):
            return _err(403, '无权管理本比赛基础数据')
        name = (name or '').strip()
        if not name:
            return _err(400, '缺少区域名称')
        cards = None
        if isinstance(request.data, dict):
            cards = request.data.get('cards')
        if cards is None and isinstance(request.data, list):
            cards = request.data
        if not isinstance(cards, list):
            return _err(400, 'cards 必须是数组')

        cleaned = []
        for index, card in enumerate(cards):
            if not isinstance(card, dict) or not str(card.get('displayName') or '').strip():
                return _err(400, '每张数据框必须包含 displayName')
            cleaned.append({
                'id': str(card.get('id') or f'c-{index + 1}'),
                'displayName': str(card.get('displayName')).strip(),
                'companyId': card.get('companyId'),
                'industryFieldId': card.get('industryFieldId'),
                'zone': card.get('zone') or 'bottom',
            })
        region, _created = Region.objects.get_or_create(name=name)
        region.overview_cards = cleaned
        region.save(update_fields=['overview_cards', 'updated_at'])
        return Response({'success': True})


def _resolve_product_name(product_id) -> str:
    if not product_id:
        return ''
    from apps.competition.basedata.models import Product
    product = Product.objects.filter(pk=product_id).first()
    return product.name if product else ''


class RegionListView(APIView):
    """GET /api/competitions/{cid}/regions（含需求数）；POST 新建区域。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _err(403, '仅比赛成员可操作')
        counts = {
            row['region_id']: row['n']
            for row in ConsumerDemand.objects.values('region_id').annotate(n=Count('id'))
        }
        qs = Region.objects.all()
        keyword = (request.query_params.get('q') or '').strip()
        if keyword:
            qs = qs.filter(name__icontains=keyword)
        return Response([_region_data(r, counts.get(r.id, 0)) for r in qs])

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _err(403, '无权管理本比赛基础数据')
        name = (request.data.get('name') or '').strip()
        if not name:
            return _err(400, '区域名称不能为空')
        if Region.objects.filter(name=name).exists():
            return _err(400, '区域名称已存在')
        region = Region.objects.create(
            name=name,
            description=request.data.get('description') or '',
        )
        return Response(_region_data(region, 0), status=status.HTTP_201_CREATED)


class RegionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        if not _require_member(request.user, cid):
            return _err(403, '仅比赛成员可操作')
        region = Region.objects.filter(pk=pk).first()
        if region is None:
            return _err(404, '区域不存在')
        return Response(_region_data(region))

    def patch(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _err(403, '无权管理本比赛基础数据')
        region = Region.objects.filter(pk=pk).first()
        if region is None:
            return _err(404, '区域不存在')
        if 'name' in request.data:
            name = (request.data.get('name') or '').strip()
            if not name:
                return _err(400, '区域名称不能为空')
            if Region.objects.filter(name=name).exclude(pk=pk).exists():
                return _err(400, '区域名称已存在')
            region.name = name
        if 'description' in request.data:
            region.description = request.data.get('description') or ''
        region.save()
        return Response(_region_data(region))

    def delete(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _err(403, '无权管理本比赛基础数据')
        region = Region.objects.filter(pk=pk).first()
        if region is None:
            return _err(404, '区域不存在')
        # 名下仍有地图节点时禁止删除（否则总览仍会从节点列出该区域，卡片配置却已丢失）
        from apps.competition.basedata.models import MapNode

        if MapNode.objects.filter(region=region.name).exists():
            return _err(400, '该区域下仍有地图节点，无法删除')
        # 删除后 ConsumerDemand 随 CASCADE 删除、Company.region 走 SET_NULL（无悬空 region_id）。
        region.delete()
        return Response({'ok': True})


class RegionOverviewCardsView(APIView):
    """GET/PUT/PATCH /regions/{pk}/overview-cards（整表替换）。

    卡片键为 industryFieldKey；提交兼容旧键 industryFieldId（写库时复制，旧配置迁移）。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        if not _require_member(request.user, cid):
            return _err(403, '仅比赛成员可操作')
        region = Region.objects.filter(pk=pk).first()
        if region is None:
            return _err(404, '区域不存在')
        return Response(region.overview_cards or [])

    def put(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _err(403, '无权管理本比赛基础数据')
        region = Region.objects.filter(pk=pk).first()
        if region is None:
            return _err(404, '区域不存在')
        cards = request.data if isinstance(request.data, list) else request.data.get('cards')
        if not isinstance(cards, list):
            return _err(400, '卡片配置必须是数组')
        normalized = []
        for card in cards:
            if not isinstance(card, dict) or not card.get('displayName'):
                return _err(400, '每张卡片必须包含 displayName')
            if 'industryFieldKey' not in card and 'industryFieldId' in card:
                card = {**card, 'industryFieldKey': card['industryFieldId']}
            normalized.append(card)
        region.overview_cards = normalized
        region.save(update_fields=['overview_cards', 'updated_at'])
        return Response(normalized)

    patch = put


def _parse_quantity(raw):
    """数量解析：接受 int 与数字字符串（含 ``'30.0'``）；非法/非整数返回 None。"""
    if raw in (None, ''):
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        pass
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else None


def _resolve_demand_region(data):
    """定位需求所属区域：regionId 优先，否则按区域名取/建（区域在地图管理里创建，总览页只拿得到名字）。"""
    region_id = data.get('regionId')
    if region_id not in (None, ''):
        region = Region.objects.filter(pk=region_id).first()
        return region, (None if region is not None else _err(400, '区域不存在'))
    name = (data.get('region') or '').strip() if isinstance(data.get('region'), str) else ''
    if name:
        region, _created = Region.objects.get_or_create(name=name)
        return region, None
    return None, _err(400, '缺少区域（regionId 或 region 区域名）')


class ConsumerDemandListView(APIView):
    """GET/POST /consumer-demands（?regionId 过滤）；POST 支持 {region: 区域名}（总览页口径）或 {regionId}。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _err(403, '仅比赛成员可操作')
        qs = ConsumerDemand.objects.select_related('region', 'product').all()
        region_id = request.query_params.get('regionId')
        if region_id and str(region_id).isdigit():
            qs = qs.filter(region_id=int(region_id))
        return Response([_demand_data(d) for d in qs])

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _err(403, '无权管理本比赛基础数据')
        region, error = _resolve_demand_region(request.data)
        if error is not None:
            return error
        quantity = _parse_quantity(request.data.get('quantity'))
        if quantity is None:
            return _err(400, '数量必须是整数')
        demand = ConsumerDemand.objects.create(
            region=region,
            product_id=request.data.get('productId') or None,
            product_name=(request.data.get('productName') or '').strip()
            or _resolve_product_name(request.data.get('productId')),
            quantity=quantity,
            note=request.data.get('note') or '',
        )
        region_services.recompute_region_demands(region.id)
        return Response(_demand_data(demand), status=status.HTTP_201_CREATED)


class ConsumerDemandDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        if not _require_member(request.user, cid):
            return _err(403, '仅比赛成员可操作')
        demand = ConsumerDemand.objects.filter(pk=pk).first()
        if demand is None:
            return _err(404, '消费者需求不存在')
        return Response(_demand_data(demand))

    def patch(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _err(403, '无权管理本比赛基础数据')
        demand = ConsumerDemand.objects.filter(pk=pk).first()
        if demand is None:
            return _err(404, '消费者需求不存在')
        old_region_id = demand.region_id
        if 'regionId' in request.data or 'region' in request.data:
            region, error = _resolve_demand_region(request.data)
            if error is not None:
                return error
            demand.region = region
        if 'productId' in request.data:
            demand.product_id = request.data.get('productId') or None
            demand.product_name = _resolve_product_name(demand.product_id)
        if 'productName' in request.data:
            demand.product_name = (request.data.get('productName') or '').strip()
        if 'quantity' in request.data:
            quantity = _parse_quantity(request.data.get('quantity'))
            if quantity is None:
                return _err(400, '数量必须是整数')
            demand.quantity = quantity
        if 'note' in request.data:
            demand.note = request.data.get('note') or ''
        demand.save()
        region_services.recompute_region_demands(old_region_id)
        if demand.region_id != old_region_id:
            region_services.recompute_region_demands(demand.region_id)
        return Response(_demand_data(demand))

    def delete(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _err(403, '无权管理本比赛基础数据')
        demand = ConsumerDemand.objects.filter(pk=pk).first()
        if demand is None:
            return _err(404, '消费者需求不存在')
        region_id = demand.region_id
        demand.delete()
        region_services.recompute_region_demands(region_id)
        return Response({'ok': True})


# ---------------------------------------------------------------- 区域字段（2026-11）
# 定义由比赛包提供（比赛级，所有区域共用一套）；值按区域存。

def _region_field_data(field, value=None) -> dict:
    return {
        'id': field.id,
        'key': field.field_key,
        'name': field.name,
        'fieldType': field.field_type,
        'defaultValue': field.default_value,
        'condition': field.condition or {},
        'value': value,
        'updatedAt': field.updated_at.isoformat(),
    }


class RegionFieldDefinitionListView(APIView):
    """GET /competitions/{cid}/region-fields：本比赛区域字段定义（比赛包导入）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _err(403, '仅比赛成员可操作')
        from apps.competition.regions.models import RegionField
        rows = RegionField.objects.all().order_by('id')
        return Response([_region_field_data(f) for f in rows])


class RegionFieldValuesByNameView(APIView):
    """GET /competitions/{cid}/regions/by-name/<name>/field-values：某区域的全部区域字段值。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, name):
        if not _require_member(request.user, cid):
            return _err(403, '仅比赛成员可操作')
        from apps.competition.regions.models import RegionField, RegionFieldValue

        region = Region.objects.filter(name=name).first()
        values = {}
        if region is not None:
            values = {
                row.field_key: row.value
                for row in RegionFieldValue.objects.filter(region=region)
            }
        rows = RegionField.objects.all().order_by('id')
        return Response([
            _region_field_data(f, values.get(f.field_key, f.default_value))
            for f in rows
        ])


class RegionFieldValueByNameView(APIView):
    """PATCH /competitions/{cid}/regions/by-name/<name>/field-values/<key>：超级管理员手工改值。"""

    permission_classes = [IsAuthenticated]

    def patch(self, request, cid, name, key):
        if not can_manage_competition(request.user, cid):
            return _err(403, '无权管理本比赛基础数据')
        from apps.competition.fieldlogs.models import FieldLog
        from apps.competition.regions.models import RegionField

        field = RegionField.objects.filter(field_key=key).first()
        if field is None:
            return _err(404, '区域字段未定义（应由比赛包提供）')

        value = request.data.get('value')
        if value is None or (isinstance(value, str) and not value.strip()):
            return _err(400, '字段值必填')

        region, _created = Region.objects.get_or_create(name=name)
        before = region_services.read_region_value(region.id, key, field.default_value)
        row = region_services.write_region_value(region.id, key, value)
        FieldLog.objects.create(
            company=None, region=region, field_key=key, data_table='REGION',
            event=FieldLog.Event.VALUE_CHANGE, op='SET',
            before_raw=before, after_raw=value, source=FieldLog.Source.MANUAL,
            operator_id=request.user.id, operator_username=request.user.username,
        )
        return Response({'key': key, 'value': row.value, 'version': row.version})
