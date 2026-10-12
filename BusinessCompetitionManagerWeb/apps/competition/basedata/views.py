"""基础数据管理 API（数据管理页）——10 类基础数据的通用 CRUD。

导入方式变更：基础数据不再随比赛包导入，改由本页在系统内维护；
比赛包只含**产业信息与合同信息**（见 docs/比赛包格式规范.md）。

权限（§15.2 口径延伸）：查看=本比赛成员；新增/编辑/删除=系统超管或本比赛超管。
"""

from django.apps import apps as django_apps
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition

# 表键 → 模型与字段映射（API camelCase → 模型字段）
TABLES = {
    'fuels': {
        'model': 'Fuel', 'label': '燃料',
        'fields': {'unit': 'unit', 'energyValue': 'energy_value', 'price': 'price'},
    },
    'warehouses': {
        'model': 'Warehouse', 'label': '仓库',
        'fields': {'capacity': 'capacity', 'regionCode': 'region_code'},
    },
    'vehicles': {
        'model': 'Vehicle', 'label': '载具',
        'fields': {
            'vehicleType': 'vehicle_type', 'loadCapacity': 'load_capacity', 'speed': 'speed',
            'fuelCode': 'fuel_code', 'fuelConsumption': 'fuel_consumption',
        },
    },
    'maps': {
        'model': 'MapRegion', 'label': '地图',
        'fields': {
            'regionType': 'region_type', 'adjacentCodes': 'adjacent_codes', 'distance': 'distance',
        },
    },
    'materials': {
        'model': 'Material', 'label': '原料',
        'fields': {'unit': 'unit', 'basePrice': 'base_price'},
    },
    'products': {
        'model': 'Product', 'label': '产品',
        'fields': {'unit': 'unit', 'basePrice': 'base_price'},
    },
    'parts': {
        'model': 'Part', 'label': '零件',
        'fields': {'unit': 'unit', 'basePrice': 'base_price', 'compatibleTypes': 'compatible_types'},
    },
    'infrastructures': {
        'model': 'Infrastructure', 'label': '基建',
        'fields': {
            'infraType': 'infra_type', 'buildCost': 'build_cost',
            'maintenanceCost': 'maintenance_cost', 'effect': 'effect',
        },
    },
    'tech_trees': {
        'model': 'TechNode', 'label': '科技树',
        'fields': {
            'tier': 'tier', 'prerequisiteCodes': 'prerequisite_codes',
            'researchCost': 'research_cost', 'effect': 'effect',
        },
    },
    'production_lines': {
        'model': 'ProductionLine', 'label': '生产线',
        'fields': {
            'inputs': 'inputs', 'outputs': 'outputs',
            'capacity': 'capacity', 'buildCost': 'build_cost',
        },
    },
}

JSON_FIELDS = {'effect', 'inputs', 'outputs', 'meta'}


def _model_for(table: str):
    spec = TABLES.get(table)
    if spec is None:
        return None, None
    return django_apps.get_model('basedata', spec['model']), spec


def _serialize(row, spec) -> dict:
    data = {'id': row.id, 'code': row.code, 'name': row.name, 'notes': row.notes,
            'meta': row.meta}
    for api_key, model_field in spec['fields'].items():
        data[api_key] = getattr(row, model_field)
    return data


def _apply_fields(model, row, payload: dict, spec, *, creating=False):
    """把 API 字段写入模型实例；未知字段忽略，返回错误列表。"""
    errors = []
    if 'code' in payload or creating:
        code = str(payload.get('code') or '').strip()
        if not code:
            errors.append('编码必填')
        else:
            row.code = code
    if 'name' in payload or creating:
        name = str(payload.get('name') or '').strip()
        if not name:
            errors.append('名称必填')
        else:
            row.name = name
    if 'notes' in payload:
        row.notes = str(payload.get('notes') or '')
    if 'meta' in payload and isinstance(payload.get('meta'), dict):
        row.meta = payload['meta']
    for api_key, model_field in spec['fields'].items():
        if api_key not in payload:
            continue
        value = payload[api_key]
        if model_field in JSON_FIELDS and not isinstance(value, (dict, list)):
            errors.append(f'{api_key} 应为对象/数组')
            continue
        setattr(row, model_field, value)
    return errors


class BasedataTableView(APIView):
    """GET 列表（关键字过滤 code/name + 分页）；POST 新增。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, table):
        model, spec = _model_for(table)
        if model is None:
            return Response({'code': 404, 'message': '未知数据表', 'details': table}, status=404)
        qs = model.objects.all()
        keyword = (request.query_params.get('q') or '').strip()
        if keyword:
            qs = qs.filter(Q(code__icontains=keyword) | Q(name__icontains=keyword))
        page = max(int(request.query_params.get('page', 1) or 1), 1)
        page_size = min(int(request.query_params.get('pageSize', 200) or 200), 500)
        total = qs.count()
        rows = qs.order_by('code')[(page - 1) * page_size: page * page_size]
        return Response({
            'items': [_serialize(r, spec) for r in rows],
            'total': total, 'page': page, 'pageSize': page_size,
            'table': table, 'label': spec['label'],
        })

    def post(self, request, cid, table):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '没有权限执行此操作', 'details': ''}, status=403)
        model, spec = _model_for(table)
        if model is None:
            return Response({'code': 404, 'message': '未知数据表', 'details': table}, status=404)
        row = model()
        errors = _apply_fields(model, row, request.data, spec, creating=True)
        if errors:
            return Response({'code': 400, 'message': '；'.join(errors), 'details': ''}, status=400)
        if model.objects.filter(code=row.code).exists():
            return Response({'code': 400, 'message': f'编码 {row.code} 已存在', 'details': ''}, status=400)
        row.save()
        return Response(_serialize(row, spec), status=status.HTTP_201_CREATED)


class BasedataRowView(APIView):
    """PATCH 编辑；DELETE 删除。"""

    permission_classes = [IsAuthenticated]

    def _row(self, cid, table, pk):
        model, spec = _model_for(table)
        if model is None:
            return None, None, Response({'code': 404, 'message': '未知数据表', 'details': table}, status=404)
        row = model.objects.filter(pk=pk).first()
        if row is None:
            return None, None, Response({'code': 404, 'message': '记录不存在', 'details': ''}, status=404)
        return row, spec, None

    def patch(self, request, cid, table, pk):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '没有权限执行此操作', 'details': ''}, status=403)
        row, spec, denied = self._row(cid, table, pk)
        if denied:
            return denied
        errors = _apply_fields(type(row), row, request.data, spec)
        if errors:
            return Response({'code': 400, 'message': '；'.join(errors), 'details': ''}, status=400)
        if 'code' in request.data:
            exists = type(row).objects.filter(code=row.code).exclude(pk=row.pk).exists()
            if exists:
                return Response({'code': 400, 'message': f'编码 {row.code} 已存在', 'details': ''}, status=400)
        row.save()
        return Response(_serialize(row, spec))

    def delete(self, request, cid, table, pk):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '没有权限执行此操作', 'details': ''}, status=403)
        row, spec, denied = self._row(cid, table, pk)
        if denied:
            return denied
        row.delete()
        return Response({'ok': True})
