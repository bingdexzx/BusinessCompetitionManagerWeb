"""基础数据管理 API（数据管理页）——统一通用契约（前后端并行开发口径）。

路由：/basedata/{table}（GET/POST）、/basedata/{table}/{id}（GET/PATCH/DELETE）、.../{id}/impact；
table ∈ fuels|warehouses|vehicles|materials|products|parts|infrastructures|tech_nodes|
production_lines|map_node_types|path_types|map_nodes|map_edges（旧模型 db_table）。
行字段 camelCase（pricePerLiter、fuelConsumptionPerKm…），Decimal(60,4) 金额按旧口径序列化为数值；
GET 带 relations，POST/PATCH 可提交嵌套 relations 整体替换（带 id 更新、无 id 新增、缺失删除）。
权限：读=本比赛成员，写=can_manage_competition；错误响应 {code, message, details}。
"""

from django.conf import settings

from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition, can_read_competition
from apps.common.context import get_competition_alias


def _f(api, field, kind, **kw):
    return dict(api=api, field=field, kind=kind, **kw)


TABLES = {
    'fuels': {
        'model': 'Fuel', 'label': '燃料',
        'fields': [
            _f('name', 'name', 'char'),
            _f('pricePerLiter', 'price_per_liter', 'decimal'),
        ],
        'required': ['name', 'pricePerLiter'],
    },
    'warehouses': {
        'model': 'Warehouse', 'label': '仓库',
        'fields': [
            _f('name', 'name', 'char'),
            _f('capacity', 'capacity', 'decimal'),
            _f('price', 'price', 'decimal'),
            _f('type', 'type', 'char'),
        ],
        'required': ['name', 'capacity', 'price', 'type'],
    },
    'vehicles': {
        'model': 'Vehicle', 'label': '载具',
        'fields': [
            _f('name', 'name', 'char'),
            _f('fuelId', 'fuel', 'fk', target='Fuel'),
            _f('fuelConsumptionPerKm', 'fuel_consumption_per_km', 'float'),
            _f('maxMaterialCargo', 'max_material_cargo', 'float'),
            _f('maxPartCargo', 'max_part_cargo', 'float'),
            _f('maxProductCargo', 'max_product_cargo', 'float'),
            _f('price', 'price', 'decimal'),
            _f('carbonEmission', 'carbon_emission', 'float'),
        ],
        'required': ['name', 'fuelId', 'fuelConsumptionPerKm', 'price', 'carbonEmission'],
    },
    'materials': {
        'model': 'Material', 'label': '原料',
        'fields': [
            _f('name', 'name', 'char'),
            _f('origin', 'origin', 'char'),
            _f('carbonEmissionCoefficient', 'carbon_emission_coefficient', 'float'),
            _f('nodePrices', 'node_prices', 'text'),
        ],
        'required': ['name', 'origin', 'carbonEmissionCoefficient'],
    },
    'products': {
        'model': 'Product', 'label': '产品',
        'fields': [
            _f('name', 'name', 'char'),
        ],
        'required': ['name'],
    },
    'parts': {
        'model': 'Part', 'label': '零件',
        'fields': [
            _f('name', 'name', 'char'),
        ],
        'required': ['name'],
    },
    'infrastructures': {
        'model': 'Infrastructure', 'label': '基建',
        'fields': [
            _f('name', 'name', 'char'),
            _f('footprint', 'footprint', 'float'),
            _f('employmentRateBonus', 'employment_rate_bonus', 'float'),
            _f('populationBonus', 'population_bonus', 'float'),
            _f('highQualityPopulationBonus', 'high_quality_population_bonus', 'float'),
            _f('price', 'price', 'decimal'),
            _f('happinessIndexBonus', 'happiness_index_bonus', 'float'),
            _f('perCapitaIncomeBonus', 'per_capita_income_bonus', 'float'),
            _f('carbonReductionBonus', 'carbon_reduction_bonus', 'float'),
            _f('activationPrice', 'activation_price', 'decimal'),
        ],
        'required': ['name', 'footprint', 'price', 'activationPrice'],
    },
    'tech_nodes': {
        'model': 'TechNode', 'label': '科技树',
        'fields': [
            _f('name', 'name', 'char'),
            _f('description', 'description', 'text'),
            _f('researchCost', 'research_cost', 'float'),
        ],
        'required': ['name'],
    },
    'production_lines': {
        'model': 'ProductionLine', 'label': '生产线',
        'fields': [
            _f('name', 'name', 'char'),
            _f('price', 'price', 'decimal'),
            _f('laborCount', 'labor_count', 'int'),
            _f('maxPerYear', 'max_per_year', 'decimal'),
        ],
        'required': ['name', 'price', 'laborCount', 'maxPerYear'],
    },
    'map_node_types': {
        'model': 'MapNodeType', 'label': '地图节点类型',
        'fields': [
            _f('name', 'name', 'char'),
            _f('description', 'description', 'text'),
            _f('color', 'color', 'char'),
        ],
        'required': ['name'],
    },
    'path_types': {
        'model': 'PathType', 'label': '路径类型',
        'fields': [
            _f('name', 'name', 'char'),
            _f('description', 'description', 'text'),
            _f('color', 'color', 'char'),
        ],
        'required': ['name'],
    },
    'map_nodes': {
        'model': 'MapNode', 'label': '地图节点',
        'fields': [
            _f('name', 'name', 'char'),
            _f('region', 'region', 'char'),
            _f('nodeTypeId', 'node_type', 'fk', target='MapNodeType'),
            _f('x', 'x', 'float'),
            _f('y', 'y', 'float'),
        ],
        'required': ['name', 'nodeTypeId'],
    },
    'map_edges': {
        'model': 'MapEdge', 'label': '地图边',
        'fields': [
            _f('fromNodeId', 'from_node', 'fk', target='MapNode'),
            _f('toNodeId', 'to_node', 'fk', target='MapNode'),
            _f('distance', 'distance', 'float'),
            _f('path', 'path', 'json'),
            _f('pathTypeId', 'path_type', 'fk', target='PathType'),
        ],
        'required': ['fromNodeId', 'toNodeId', 'pathTypeId'],
    },
}

# 关联内嵌定义（照旧关联模型）：assoc=关联模型，parent/target=指向本行/目标主数据的外键，
# out=额外读出字段（ratio），names=目标主数据名称字段（照旧嵌套展示 partName 等）。
RELATIONS = {
    'products': {
        'parts': {
            'assoc': 'ProductPart', 'parent': 'product', 'target': 'part',
            'target_model': 'Part', 'name_field': 'partName',
            'writable': {'partId': 'part', 'ratio': 'ratio'},
            'create_required': ['partId', 'ratio'], 'extra': ['ratio'],
        },
        'techRequirements': {
            'assoc': 'ProductTechRequirement', 'parent': 'product', 'target': 'tech_node',
            'target_model': 'TechNode', 'name_field': 'techNodeName',
            'writable': {'techNodeId': 'tech_node'}, 'create_required': ['techNodeId'],
            'extra': [],
        },
    },
    'parts': {
        'materials': {
            'assoc': 'PartMaterial', 'parent': 'part', 'target': 'material',
            'target_model': 'Material', 'name_field': 'materialName',
            'writable': {'materialId': 'material', 'ratio': 'ratio'},
            'create_required': ['materialId', 'ratio'], 'extra': ['ratio'],
        },
        'techRequirements': {
            'assoc': 'PartTechRequirement', 'parent': 'part', 'target': 'tech_node',
            'target_model': 'TechNode', 'name_field': 'techNodeName',
            'writable': {'techNodeId': 'tech_node'}, 'create_required': ['techNodeId'],
            'extra': [],
        },
    },
    'tech_nodes': {
        'prerequisites': {
            'assoc': 'TechPrerequisite', 'parent': 'node', 'target': 'prerequisite',
            'target_model': 'TechNode', 'name_field': 'prerequisiteName',
            'writable': {'prerequisiteId': 'prerequisite'},
            'create_required': ['prerequisiteId'], 'extra': [],
        },
    },
    'vehicles': {
        'pathTypes': {
            'assoc': 'VehiclePathType', 'parent': 'vehicle', 'target': 'path_type',
            'target_model': 'PathType', 'name_field': 'pathTypeName',
            'writable': {'pathTypeId': 'path_type'}, 'create_required': ['pathTypeId'],
            'extra': [],
        },
    },
    'map_nodes': {
        'edgesCount': {'kind': 'count'},
    },
}

# 删除影响（旧 get_delete_impact 语义）：(kind, label, 取数函数, 是否外部引用)；外部引用即
# removable=False，指引用行归属其他主数据（fuel←vehicles、part←products、map_node←map_edges）。


def _impact_fuels(pk):
    from .models import Vehicle
    return [('vehicles', '关联的载具', Vehicle.objects.filter(fuel_id=pk).count(), True)]


def _impact_vehicles(pk):
    from .models import VehiclePathType
    return [('vehicle_path_types', '支持的路径类型',
             VehiclePathType.objects.filter(vehicle_id=pk).count(), False)]


def _impact_map_node_types(pk):
    from .models import MapEdge, MapNode
    node_count = MapNode.objects.filter(node_type_id=pk).count()
    edge_count = (
        MapEdge.objects.filter(from_node__node_type_id=pk).count()
        + MapEdge.objects.filter(to_node__node_type_id=pk).count()
    )
    return [
        ('map_nodes', '下属地图节点（含其关联地图边）', node_count, True),
        ('map_edges', '关联的地图边', edge_count, True),
    ]


def _impact_path_types(pk):
    from .models import MapEdge, VehiclePathType
    return [
        ('map_edges', '使用该类型的地图边', MapEdge.objects.filter(path_type_id=pk).count(), True),
        ('vehicle_path_types', '载具通行配置',
         VehiclePathType.objects.filter(path_type_id=pk).count(), True),
    ]


def _impact_map_nodes(pk):
    from .models import MapEdge
    return [('map_edges', '关联的地图边',
             MapEdge.objects.filter(Q(from_node_id=pk) | Q(to_node_id=pk)).count(), True)]


def _impact_materials(pk):
    from .models import PartMaterial
    return [('part_materials', '关联的零件配比关系',
             PartMaterial.objects.filter(material_id=pk).count(), True)]


def _impact_products(pk):
    from .models import ProductPart, ProductTechRequirement
    return [
        ('product_parts', '零件配比关系', ProductPart.objects.filter(product_id=pk).count(), False),
        ('product_tech_requirements', '科技树需求关联',
         ProductTechRequirement.objects.filter(product_id=pk).count(), False),
    ]


def _impact_parts(pk):
    from .models import PartMaterial, PartTechRequirement, ProductPart
    return [
        ('part_materials', '原料配比关系', PartMaterial.objects.filter(part_id=pk).count(), False),
        ('product_parts', '作为组件被产品引用', ProductPart.objects.filter(part_id=pk).count(), True),
        ('part_tech_requirements', '科技树需求关联',
         PartTechRequirement.objects.filter(part_id=pk).count(), False),
    ]


def _impact_tech_nodes(pk):
    from .models import PartTechRequirement, ProductTechRequirement, TechPrerequisite
    return [
        ('part_tech_requirements', '零件科技需求',
         PartTechRequirement.objects.filter(tech_node_id=pk).count(), True),
        ('product_tech_requirements', '产品科技需求',
         ProductTechRequirement.objects.filter(tech_node_id=pk).count(), True),
        ('tech_prerequisites', '该节点的前提依赖关系',
         TechPrerequisite.objects.filter(node_id=pk).count(), False),
        ('tech_prerequisites', '以该科技为前提的科技关系',
         TechPrerequisite.objects.filter(prerequisite_id=pk).count(), True),
    ]


IMPACTS = {
    'fuels': _impact_fuels,
    'warehouses': lambda pk: [],
    'vehicles': _impact_vehicles,
    'map_node_types': _impact_map_node_types,
    'path_types': _impact_path_types,
    'map_nodes': _impact_map_nodes,
    'map_edges': lambda pk: [],
    'materials': _impact_materials,
    'products': _impact_products,
    'parts': _impact_parts,
    'infrastructures': lambda pk: [],
    'tech_nodes': _impact_tech_nodes,
    'production_lines': lambda pk: [],
}

# 列表检索字段（q 过滤；map_edges 无 name，按起终点名/ID 检索）
SEARCH_FIELDS = {
    'map_edges': ['from_node__name', 'to_node__name'],
}


def _error(message, code=400, details=''):
    """统一业务错误响应（{code, message, details}，中文）。"""
    return Response({'code': code, 'message': message, 'details': details}, status=code)


def _require_member(user, cid):
    """读权限：本比赛成员（系统超级管理员恒通过）——实现在 apps.common.authority。"""
    return can_read_competition(user, cid)


def _model_for(table):
    spec = TABLES.get(table)
    if spec is None:
        return None, None
    from django.apps import apps as django_apps
    return django_apps.get_model('basedata', spec['model']), spec


def _db_alias():
    return get_competition_alias() or 'default'


def _decimal_out(value):
    """Decimal(60,4) 金额按旧系统 JSON 口径输出为数值。"""
    return None if value is None else float(value)


def _field_out(row, fdef):
    if fdef['kind'] == 'fk':
        return getattr(row, fdef['field'] + '_id')
    value = getattr(row, fdef['field'])
    if fdef['kind'] == 'decimal':
        return _decimal_out(value)
    return value


def _serialize_relations_many(rows, table):
    """批量构造 relations（列表/详情共用，避免 N+1）。"""
    from django.apps import apps as django_apps

    result = {row.pk: {} for row in rows}
    rel_spec = RELATIONS.get(table, {})
    ids = [row.pk for row in rows]
    if not ids:
        return result

    for key, spec in rel_spec.items():
        if spec.get('kind') == 'count':
            from .models import MapEdge
            counts = {pk: 0 for pk in ids}
            for edge in MapEdge.objects.filter(
                Q(from_node_id__in=ids) | Q(to_node_id__in=ids)
            ).only('from_node_id', 'to_node_id'):
                if edge.from_node_id in counts:
                    counts[edge.from_node_id] += 1
                if edge.to_node_id in counts and edge.to_node_id != edge.from_node_id:
                    counts[edge.to_node_id] += 1
            for pk in ids:
                result[pk][key] = counts[pk]
            continue

        assoc_model = django_apps.get_model('basedata', spec['assoc'])
        target_model = django_apps.get_model('basedata', spec['target_model'])
        parent_field, target_field = spec['parent'], spec['target']
        target_api = next(k for k, v in spec['writable'].items() if v == target_field)
        assocs = list(assoc_model.objects.filter(
            **{f'{parent_field}_id__in': ids},
        ).order_by('id'))
        target_ids = {getattr(a, target_field + '_id') for a in assocs}
        names = dict(target_model.objects.filter(pk__in=target_ids)
                     .values_list('id', 'name')) if target_ids else {}
        grouped = {pk: [] for pk in ids}
        for a in assocs:
            item = {
                'id': a.pk,
                target_api: getattr(a, target_field + '_id'),
                spec['name_field']: names.get(getattr(a, target_field + '_id')),
            }
            for extra in spec['extra']:
                item[extra] = getattr(a, extra)
            grouped[getattr(a, parent_field + '_id')].append(item)
        for pk in ids:
            result[pk][key] = grouped[pk]
    return result


def _serialize_many(rows, table):
    spec = TABLES[table]
    rels = _serialize_relations_many(rows, table)
    items = []
    for row in rows:
        data = {'id': row.pk}
        for fdef in spec['fields']:
            data[fdef['api']] = _field_out(row, fdef)
        data['createdAt'] = row.created_at
        data['updatedAt'] = row.updated_at
        data['relations'] = rels.get(row.pk, {})
        items.append(data)
    return items


def _coerce_value(fdef, value):
    """API 值 → 模型值；失败抛 ValueError（中文消息）。"""
    kind = fdef['kind']
    if value is None:
        return None
    if kind in ('char', 'text'):
        if not isinstance(value, str):
            value = str(value)
        return value
    if kind == 'json':
        if not isinstance(value, (list, dict)):
            raise ValueError(f"{fdef['api']} 需要数组或对象")
        return value
    if kind == 'int':
        try:
            fval = float(value)
            ival = int(fval)
            if fval != ival:
                raise ValueError
            return ival
        except (TypeError, ValueError):
            raise ValueError(f"{fdef['api']} 不是整数")
    if kind == 'float':
        try:
            fval = float(value)
            if fval != fval or fval in (float('inf'), float('-inf')):
                raise ValueError
            return fval
        except (TypeError, ValueError):
            raise ValueError(f"{fdef['api']} 不是数值")
    if kind == 'decimal':
        try:
            dval = Decimal(str(value))
            if not dval.is_finite():
                raise ValueError
            return dval
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"{fdef['api']} 不是有效金额")
    if kind == 'fk':
        try:
            ivalue = int(value)
            if ivalue <= 0:
                raise ValueError
            return ivalue
        except (TypeError, ValueError):
            raise ValueError(f"{fdef['api']} 不是有效 ID")
    raise ValueError(f"{fdef['api']} 类型未知")


def _apply_payload(row, spec, payload, creating):
    """把 API 字段写入模型实例；返回错误列表（中文）。"""
    from django.apps import apps as django_apps

    errors = []
    for fdef in spec['fields']:
        api = fdef['api']
        if api not in payload:
            if creating and api in spec['required']:
                errors.append(f'{api} 必填')
            continue
        try:
            value = _coerce_value(fdef, payload[api])
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if value is None:
            if api in spec['required']:
                errors.append(f'{api} 不能为空')
            else:
                setattr(row, fdef['field'] + ('_id' if fdef['kind'] == 'fk' else ''), None)
            continue
        if fdef['kind'] in ('char', 'text'):
            max_length = getattr(
                type(row)._meta.get_field(fdef['field']), 'max_length', None)
            if max_length and len(value) > max_length:
                errors.append(f'{api} 超长（最多 {max_length} 字符）')
                continue
            if fdef['kind'] == 'char' and api in spec['required'] and not value.strip():
                errors.append(f'{api} 不能为空')
                continue
        if fdef['kind'] == 'fk':
            target_model = django_apps.get_model('basedata', fdef['target'])
            if not target_model.objects.filter(pk=value).exists():
                errors.append(f"{api} 指向的{TABLES_BY_MODEL[fdef['target']]['label']}不存在")
                continue
            setattr(row, fdef['field'] + '_id', value)
            continue
        setattr(row, fdef['field'], value)
    return errors


TABLES_BY_MODEL = {spec['model']: spec for spec in TABLES.values()}


def _relation_items(payload, key):
    """取关联数组：优先嵌套 relations.<key>，兼容平铺同名数组（别名）。"""
    rels = payload.get('relations')
    if isinstance(rels, dict) and key in rels:
        return rels[key]
    if key in payload:
        return payload[key]
    return None


def _replace_relations(row, table, payload):
    """关联整体替换（upsert by id）：带 id 更新、无 id 新增、缺失删除；须在事务内调用（校验失败/唯一
    冲突即抛 _ValidationAbort 回滚）。
    """
    from django.apps import apps as django_apps

    rel_spec = RELATIONS.get(table, {})
    rels = payload.get('relations')
    if rels is not None and not isinstance(rels, dict):
        return ['relations 应为对象']
    if isinstance(rels, dict):
        unknown = set(rels) - set(rel_spec)
        if unknown:
            return [f"relations 含未知关联：{'、'.join(sorted(unknown))}"]

    for key, spec in rel_spec.items():
        if spec.get('kind') == 'count':
            continue
        items = _relation_items(payload, key)
        if items is None:
            continue
        if not isinstance(items, list):
            return [f'{key} 应为数组']

        assoc_model = django_apps.get_model('basedata', spec['assoc'])
        target_model = django_apps.get_model('basedata', spec['target_model'])
        target_label = TABLES_BY_MODEL[spec['target_model']]['label']
        parent_field, target_field = spec['parent'], spec['target']
        existing = list(assoc_model.objects.filter(**{parent_field: row.pk}))
        by_id = {a.pk: a for a in existing}

        errors, pending, seen_ids, seen_targets = [], [], set(), set()
        for i, item in enumerate(items):
            prefix = f'{key}[{i}]'
            item_errors = []
            if not isinstance(item, dict):
                errors.append(f'{prefix} 应为对象')
                continue
            assoc = None
            if item.get('id') is not None:
                try:
                    assoc = by_id.get(int(item['id']))
                except (TypeError, ValueError):
                    assoc = None
                if assoc is None:
                    errors.append(f"{prefix} 关联记录不存在（id={item.get('id')}）")
                    continue
                if assoc.pk in seen_ids:
                    errors.append(f'{prefix} id 重复')
                    continue
                seen_ids.add(assoc.pk)
            # 目标外键：带 id 更新时可缺省（保持原值）
            target_id = getattr(assoc, target_field + '_id') if assoc is not None else None
            for api_key, model_field in spec['writable'].items():
                if model_field != target_field or api_key not in item:
                    continue
                try:
                    target_id = int(item[api_key])
                except (TypeError, ValueError):
                    item_errors.append(f'{prefix}.{api_key} 不是有效 ID')
            if assoc is None:
                for req in spec['create_required']:
                    if item.get(req) in (None, ''):
                        item_errors.append(f'{prefix}.{req} 必填')
            for extra in spec['extra']:
                if assoc is not None and extra in item and item[extra] is not None:
                    try:
                        float(item[extra])
                    except (TypeError, ValueError):
                        item_errors.append(f'{prefix}.{extra} 不是数值')
            if target_id is None and not item_errors:
                item_errors.append(f'{prefix} 目标引用不能为空')
            elif target_id is not None and not item_errors:
                if not target_model.objects.filter(pk=target_id).exists():
                    item_errors.append(f'{prefix} 指向的{target_label}不存在（id={target_id}）')
                elif target_id in seen_targets:
                    item_errors.append(f'{prefix} 与其他关联指向同一{target_label}')
            if item_errors:
                errors.extend(item_errors)
                continue
            seen_targets.add(target_id)
            pending.append((assoc, target_id, item))
        if errors:
            return errors

        # ---- 落库阶段：先删缺失，再 upsert（整体替换语义）
        for a in existing:
            if a.pk not in seen_ids:
                a.delete()
        for assoc, target_id, item in pending:
            if assoc is None:
                assoc = assoc_model(**{parent_field + '_id': row.pk})
            setattr(assoc, target_field + '_id', target_id)
            for extra in spec['extra']:
                if extra in item and item[extra] is not None:
                    setattr(assoc, extra, float(item[extra]))
            try:
                assoc.save()
            except IntegrityError:
                # 唯一冲突（重复关联/互换更新中间态）：中止回滚
                raise _ValidationAbort(f'{key} 关联冲突（重复或与现有关联互换）')
    return []


class BasedataTableView(APIView):
    """GET 列表（?page&pageSize&q）；POST 新增（可带 relations 嵌套）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, table):
        if not _require_member(request.user, cid):
            return _error('仅比赛成员可操作', 403)
        model, spec = _model_for(table)
        if model is None:
            return _error('未知数据表', 404, table)
        qs = model.objects.all()
        keyword = (request.query_params.get('q') or '').strip()
        if keyword:
            fields = SEARCH_FIELDS.get(table) or ['name']
            condition = Q()
            for f in fields:
                condition |= Q(**{f'{f}__icontains': keyword})
            if table == 'map_edges' and keyword.isdigit():
                condition |= Q(pk=int(keyword))
            qs = qs.filter(condition)
        if table == 'map_nodes':
            # 只取某类节点（如「城市点位」），合同下拉选项用
            node_type = (request.query_params.get('nodeType') or '').strip()
            if node_type:
                qs = qs.filter(node_type__name=node_type)
        try:
            page = max(int(request.query_params.get('page', 1) or 1), 1)
            page_size = min(
                max(int(request.query_params.get('pageSize', settings.BASEDATA_PAGE_SIZE)
                    or settings.BASEDATA_PAGE_SIZE), 1),
                settings.BASEDATA_PAGE_SIZE_MAX)
        except (TypeError, ValueError):
            return _error('分页参数无效')
        # 数据管理/合同下拉都走这个接口，读多写少：按查询参数缓存 20s；
        # 写入（basedata/files 广播）会 bump 命名空间。
        from apps.common.cache import remember

        node_type = (request.query_params.get('nodeType') or '').strip()
        cache_parts = (cid, table, keyword, node_type, page, page_size)

        def build_page():
            total = qs.count()
            rows = list(
                qs.order_by('-updated_at', '-id')[(page - 1) * page_size: page * page_size])
            return {
                'items': _serialize_many(rows, table),
                'total': total, 'page': page, 'pageSize': page_size,
            }

        return Response(remember(
            'basedata', cache_parts, build_page, timeout=settings.CACHE_TTL_BASEDATA))

    def post(self, request, cid, table):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        model, spec = _model_for(table)
        if model is None:
            return _error('未知数据表', 404, table)
        payload = request.data if isinstance(request.data, dict) else {}
        row = model()
        errors = _apply_payload(row, spec, payload, creating=True)
        if errors:
            return _error('；'.join(errors))
        try:
            with transaction.atomic(using=_db_alias()):
                row.save()
                rel_errors = _replace_relations(row, table, payload)
                if rel_errors:
                    raise _ValidationAbort('；'.join(rel_errors))
        except _ValidationAbort as exc:
            return _error(str(exc))
        except IntegrityError:
            return _error(_conflict_message(spec, row), 409)
        return Response(_serialize_many([row], table)[0], status=201)


class _ValidationAbort(Exception):
    """事务内校验失败中止（回滚后返回 400）。"""


def _conflict_message(spec, row):
    name = getattr(row, 'name', None)
    return f'名称已存在（{name}）' if name else '记录冲突'


class BasedataRowView(APIView):
    """GET 详情（含 relations）；PATCH 编辑（可带 relations 整体替换）；DELETE 删除。"""

    permission_classes = [IsAuthenticated]

    def _row(self, table, pk):
        model, spec = _model_for(table)
        if model is None:
            return None, None, _error('未知数据表', 404, table)
        row = model.objects.filter(pk=pk).first()
        if row is None:
            return None, None, _error('记录不存在', 404)
        return row, spec, None

    def get(self, request, cid, table, pk):
        if not _require_member(request.user, cid):
            return _error('仅比赛成员可操作', 403)
        row, spec, denied = self._row(table, pk)
        if denied:
            return denied
        return Response(_serialize_many([row], table)[0])

    def patch(self, request, cid, table, pk):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        row, spec, denied = self._row(table, pk)
        if denied:
            return denied
        payload = request.data if isinstance(request.data, dict) else {}
        errors = _apply_payload(row, spec, payload, creating=False)
        if errors:
            return _error('；'.join(errors))
        try:
            with transaction.atomic(using=_db_alias()):
                row.save()
                rel_errors = _replace_relations(row, table, payload)
                if rel_errors:
                    raise _ValidationAbort('；'.join(rel_errors))
        except _ValidationAbort as exc:
            return _error(str(exc))
        except IntegrityError:
            return _error(_conflict_message(spec, row), 409)
        return Response(_serialize_many([row], table)[0])

    def delete(self, request, cid, table, pk):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        row, spec, denied = self._row(table, pk)
        if denied:
            return denied
        from django.db.models import ProtectedError
        try:
            with transaction.atomic(using=_db_alias()):
                row.delete()
        except ProtectedError:
            return _error('该记录被其他数据引用，无法删除', 409)
        return Response({'ok': True})


class BasedataImpactView(APIView):
    """GET .../{id}/impact —— 删除影响检查（旧语义）：{removable, refs}。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, table, pk):
        if not _require_member(request.user, cid):
            return _error('仅比赛成员可操作', 403)
        model, spec = _model_for(table)
        if model is None:
            return _error('未知数据表', 404, table)
        if not model.objects.filter(pk=pk).exists():
            return _error('记录不存在', 404)
        refs, removable = [], True
        for kind, label, count, hard in IMPACTS[table](pk):
            if count <= 0:
                continue
            refs.append({'kind': kind, 'label': label, 'count': count})
            if hard:
                removable = False
        return Response({'removable': removable, 'refs': refs})


class MapSettingsView(APIView):
    """GET .../basedata/map-settings —— 地图坐标模式与地理范围（QGIS 导入后为 GEO）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _error('仅比赛成员可操作', 403)
        from apps.competition.basedata.models import MapSettings

        settings = MapSettings.load()
        return Response({
            'mode': settings.mode,
            'bounds': settings.bounds or [],
            'regions': settings.regions or [],
            'layers': settings.layers or [],
            'source': settings.source,
            'importedAt': settings.imported_at.isoformat() if settings.imported_at else None,
        })


class MapImportView(APIView):
    """POST .../basedata/map-import —— 导入 QGIS 工程（点→节点、线→边、面→区域）。

    请求：multipart `file`，只接受 `.qgz` 工程（内含 shp 数据源；`.zip` 内含 `.qgz` 也兼容）；
    `replace=true` 时先清空现有地图节点/边再导入（幂等：同名节点复用、重复边跳过）。
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        import tempfile
        import zipfile
        from pathlib import Path

        from apps.competition.basedata.map_import import GeoJSONError
        from apps.competition.basedata.map_import_qgis import import_qgis_project

        upload = request.FILES.get('file')
        replace = str(request.data.get('replace', '') or '').lower() in ('1', 'true', 'yes', 'on')
        if upload is None:
            return _error('请上传 QGIS 工程文件（.qgz）', 400)

        name = (upload.name or '').lower()
        if not name.endswith(('.qgz', '.zip')):
            return _error('请上传 QGIS 工程文件（.qgz）', 400)

        try:
            if name.endswith('.qgz'):
                with tempfile.TemporaryDirectory(prefix='qgis_project_') as tmp:
                    target = Path(tmp) / 'project.qgz'
                    with target.open('wb') as handle:
                        for chunk in upload.chunks():
                            handle.write(chunk)
                    report = import_qgis_project(target, replace=replace)
            else:
                # 兼容「.qgz + 同目录 shp 一起打成 ZIP」的包（qgz 本身不含图层数据源）
                with tempfile.TemporaryDirectory(prefix='qgis_zip_') as tmp:
                    target = Path(tmp) / 'project.zip'
                    with target.open('wb') as handle:
                        for chunk in upload.chunks():
                            handle.write(chunk)
                    with zipfile.ZipFile(target) as archive:
                        archive.extractall(tmp)
                    projects = list(Path(tmp).rglob('*.qgz'))
                    if not projects:
                        return _error('压缩包中没有 .qgz 工程文件', 400)
                    report = import_qgis_project(projects[0], replace=replace)
        except GeoJSONError as exc:
            return _error(str(exc), 400)
        return Response(report, status=201)
