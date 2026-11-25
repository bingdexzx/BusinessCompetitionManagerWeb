"""把地图上的矿点按「最近的城市点位」归入原料。

规则（2026-11 需求）：
- 每个矿点都属于它最近的**城市点位**节点；
- 同一矿种只建一条原料（``Material.name`` 唯一），产地收集所有邻近城市；
- 按地点价格 ``node_prices`` 预先给每个城市建一条空价（0），价格与碳排系数后续再填；
- 幂等：已有原料只补缺的城市与空价，绝不覆盖人工填过的价格。
"""
from __future__ import annotations

import json

from django.db import transaction

from apps.common.context import get_competition_alias

from .models import MapNode, Material

MINE_NODE_TYPE = '矿点'
CITY_NODE_TYPE = '城市点位'


def _load_origin(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [part.strip() for part in str(value).split(',') if part.strip()]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return [part.strip() for part in str(value).split(',') if part.strip()]


def _load_prices(value) -> dict[str, float]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): parsed[key] for key in parsed}


def plan_mine_materials() -> dict:
    """算出「矿种 → 邻近城市」的规划（不写库）。"""
    nodes = list(MapNode.objects.select_related('node_type').all())
    mines = [node for node in nodes if node.node_type.name == MINE_NODE_TYPE]
    cities = [node for node in nodes if node.node_type.name == CITY_NODE_TYPE]

    plan: dict[str, dict] = {}
    unmatched: list[str] = []
    for mine in mines:
        if not cities:
            unmatched.append(mine.name)
            continue
        nearest = min(
            cities,
            key=lambda city: (city.x - mine.x) ** 2 + (city.y - mine.y) ** 2,
        )
        entry = plan.setdefault(mine.name, {'cities': {}, 'mines': 0})
        entry['cities'][nearest.id] = nearest.name
        entry['mines'] += 1

    return {'plan': plan, 'mines': len(mines), 'cities': len(cities),
            'unmatched': unmatched,
            'node_ids': {str(node.id) for node in nodes}}


def sync_mine_materials(*, apply: bool = False) -> dict:
    """按规划创建/补齐原料；apply=False 只算不写。"""
    computed = plan_mine_materials()
    plan = computed['plan']
    existing = {material.name: material for material in Material.objects.all()}

    to_create: list[Material] = []
    to_update: list[Material] = []
    unchanged = 0
    details = []

    for ore in sorted(plan):
        entry = plan[ore]
        city_ids = sorted(entry['cities'])
        city_names = sorted({entry['cities'][city_id] for city_id in city_ids})
        material = existing.get(ore)
        details.append({
            'name': ore,
            'mines': entry['mines'],
            'cities': city_names,
            'exists': material is not None,
        })
        if material is None:
            to_create.append(Material(
                name=ore,
                origin=json.dumps(city_names, ensure_ascii=False),
                node_prices=json.dumps({str(city_id): 0 for city_id in city_ids}),
                carbon_emission_coefficient=0.0,
            ))
            continue

        origins = _load_origin(material.origin)
        prices = _load_prices(material.node_prices)
        # 地图重导后节点 id 会变：清掉指向已不存在节点的价格，避免脏数据越积越多
        alive = computed['node_ids']
        pruned = {key: value for key, value in prices.items() if key in alive}
        changed = len(pruned) != len(prices)
        prices = pruned
        for name in city_names:
            if name not in origins:
                origins.append(name)
                changed = True
        for city_id in city_ids:
            if str(city_id) not in prices:
                prices[str(city_id)] = 0
                changed = True
        if not changed:
            unchanged += 1
            continue
        material.origin = json.dumps(sorted(origins), ensure_ascii=False)
        material.node_prices = json.dumps(
            {key: prices[key] for key in sorted(prices)}, ensure_ascii=False)
        to_update.append(material)

    report = {
        'applied': False,
        'mines': computed['mines'],
        'cities': computed['cities'],
        'materials': len(plan),
        'created': len(to_create),
        'updated': len(to_update),
        'unchanged': unchanged,
        'unmatched': computed['unmatched'],
        'details': details,
        'changed': bool(to_create or to_update),
    }
    if not apply or not report['changed']:
        return report

    alias = get_competition_alias() or 'default'
    with transaction.atomic(using=alias):
        if to_create:
            Material.objects.bulk_create(to_create)
        for material in to_update:
            material.save(update_fields=['origin', 'node_prices', 'updated_at'])
    report['applied'] = True
    return report
