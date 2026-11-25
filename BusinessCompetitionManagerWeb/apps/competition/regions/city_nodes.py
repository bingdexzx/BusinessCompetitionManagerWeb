"""地图节点 → 所属城市（2026-11）。

命名规律（来自真实地图数据 comp_51，共 48 个城市点位）：

| 节点类型 | 命名样例 | 规律 |
|---|---|---|
| 城市点位 | 北安 / 泉山 / 樟港 | 城市本体（权威名单） |
| 行政区域划分 | 长平省 | 省级面，不参与归属 |
| 火车站 / 高速口 | 松平南、河平西、安山东 | `城市名 + 方位（东南西北）` |
| 码头 | 峰安南港、梁溪北港、平泽港 | `城市名 + 方位 + 港`，也有直接 `城市名 + 港` |
| 机场 | 长平国际机场、平泽南机场 | `城市名 + （方位）+ 机场` |
| 矿点 | 煤 / 石灰 / 可燃冰 | 名字是矿种，不含城市 → 按坐标取就近城市 |
| 默认节点 | 节点(x,y) | 无城市信息 → 按坐标取就近城市 |

匹配顺序（每一步都记进摘要，便于人工复核）：

1. ``prefix``：节点名以某个城市名开头（最长匹配优先）；
2. ``suffix-strip``：去掉方位/设施后缀后与城市名完全相同；
3. ``fuzzy-region``：同省城市里编辑距离 ≤1 的名字（抓「漳港 → 樟港」这类错别字）；
4. ``first-char-region``：同省城市里首字相同（兜底）；
5. ``nearest``：名字里没有城市信息时，按坐标取最近城市（优先同省城市）。
"""

from __future__ import annotations


from . import nodes as region_nodes

# 设施/方位后缀（长的优先，避免「国际机场」被拆成「机场」）
SUFFIXES = (
    '国际机场', '南部机场', '北部机场', '东部机场', '西部机场',
    '国际码头', '国内码头',
    '机场', '码头', '车站', '火车站', '高速口',
    '东南', '西南', '东北', '西北',
    '港', '站', '东', '南', '西', '北',
)

CITY_NODE_TYPE = '城市点位'
EXCLUDED_NODE_TYPES = (CITY_NODE_TYPE, '行政区域划分')


def _edit_distance_within_one(a: str, b: str) -> bool:
    """a、b 的编辑距离是否 ≤1（够用于中文错别字/同音字）。"""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    skipped = False
    while i < len(short) and j < len(long):
        if short[i] == long[j]:
            i += 1
            j += 1
            continue
        if skipped:
            return False
        skipped = True
        j += 1
    return True


def _strip_suffix(name: str) -> str:
    for suffix in SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def city_index():
    """城市名单：{城市名: 区域名}（来源：城市点位节点）。"""
    from apps.competition.basedata.models import MapNode

    index = {}
    for name, region in (MapNode.objects
                         .filter(node_type__name=CITY_NODE_TYPE)
                         .values_list('name', 'region')):
        city = region_nodes.normalize_region_name(name)
        if city:
            index[city] = region_nodes.normalize_region_name(region)
    return index


def _resolve_by_name(name: str, region: str, cities: dict):
    """按命名规律找城市：返回 (city, rule)。"""
    if not name:
        return '', 'unmatched'
    normalized = region_nodes.normalize_region_name(name)
    for city in sorted(cities, key=len, reverse=True):
        if normalized.startswith(city):
            return city, 'prefix'

    stripped = _strip_suffix(normalized)
    if stripped in cities:
        return stripped, 'suffix-strip'
    if normalized in cities:
        return normalized, 'suffix-strip'

    same_region = [city for city, city_region in cities.items()
                   if region and city_region == region]
    for city in same_region:
        if _edit_distance_within_one(city, stripped):
            return city, 'fuzzy-region'
    for city in same_region:
        if city[0] == stripped[0]:
            return city, 'first-char-region'
    return '', 'unmatched'


def _nearest_city(node, city_points):
    """按坐标取最近城市：优先同省城市，其次全部城市。返回 (city, region)。"""
    candidates = [item for item in city_points if item[1] and item[1] == node.region]
    pool = candidates or city_points
    if not pool:
        return '', ''
    best = min(pool, key=lambda item: (item[2] - float(node.x)) ** 2 + (item[3] - float(node.y)) ** 2)
    return best[0], best[1]


def assign_nodes_to_cities(*, node_types=None, overwrite: bool = False,
                           use_nearest: bool = True, fill_region: bool = True,
                           dry_run: bool = False) -> dict:
    """把车站/机场/码头/矿点等其他节点归属到所属城市。

    - ``node_types``：只处理这些节点类型名（默认除「城市点位」「行政区域划分」外的全部）；
    - ``overwrite``：False 时已有 city 的节点跳过；
    - ``use_nearest``：名字里没有城市信息时按坐标取最近城市；
    - ``fill_region``：节点 region 为空时，用城市所属区域补上。
    """
    from apps.competition.basedata.models import MapNode

    cities = city_index()
    city_points = []
    for node in MapNode.objects.filter(node_type__name=CITY_NODE_TYPE):
        region = region_nodes.normalize_region_name(node.region)
        city_points.append((region_nodes.normalize_region_name(node.name), region,
                            float(node.x), float(node.y)))

    query = MapNode.objects.select_related('node_type').exclude(
        node_type__name__in=EXCLUDED_NODE_TYPES)
    if node_types:
        wanted = {str(name) for name in node_types}
        query = query.filter(node_type__name__in=wanted)

    rules = {}
    updated = 0
    unmatched = []
    for node in query:
        if node.city and not overwrite:
            continue
        city, rule = _resolve_by_name(node.name, node.region, cities)
        if not city and use_nearest:
            city, city_region = _nearest_city(node, city_points)
            rule = 'nearest' if city else 'unmatched'
            if city and fill_region and not node.region and city_region:
                node.region = city_region
        rules[rule] = rules.get(rule, 0) + 1
        if not city:
            unmatched.append({'type': node.node_type.name, 'name': node.name,
                              'region': node.region})
            continue
        if city == node.city:
            continue
        if fill_region and not node.region:
            node.region = cities.get(city, '')
        node.city = city
        if not dry_run:
            node.save(update_fields=['city', 'region', 'updated_at'])
        updated += 1

    return {
        'cities': len(cities),
        'updated': updated,
        'rules': rules,
        'unmatched': unmatched,
        'dryRun': dry_run,
    }
