"""把地图路网重建成「节点—弧段」图（端点吸附 + T 型接头 + 交点打断）。

- 导入新地图后调用：``rebuild_topology(apply=True)``；
- 老数据用管理命令 ``renode_map`` 重建（支持 --dry-run）。

只改 ``MapEdge`` 与「自动生成的 默认节点」：**有业务名的节点、点图层节点一律不删**，
它们的 id / 区域 / 类型保持不变；新产生的交点用 ``节点(lon,lat)`` 自动命名。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.common.context import get_competition_alias

from .map_import import NODE_COLORS
from .map_topology import SourceLine, network_of, planarize_networks
from .models import MapEdge, MapNode, MapNodeType

AUTO_NODE_TYPE = '默认节点'

# 前端/导入侧约定：像素地图 1 单位≈1km；经纬度地图按度
_PIXEL_MIN_TOLERANCE = 0.5
_PIXEL_TOLERANCE_RATIO = 0.0015
_GEO_TOLERANCE = 0.001  # ≈111m


def auto_node_name(x: float, y: float) -> str:
    return f'节点({x:.5f},{y:.5f})'


def _looks_like_lonlat(nodes: list[MapNode]) -> bool:
    sample = nodes[:200]
    return bool(sample) and all(-180 <= node.x <= 180 and -90 <= node.y <= 90
                                for node in sample)


def default_tolerance(nodes: list[MapNode]) -> float:
    """按坐标类型与地图跨度给一个合适的吸附容差。"""
    if not nodes:
        return _PIXEL_MIN_TOLERANCE
    if _looks_like_lonlat(nodes):
        return _GEO_TOLERANCE
    span = max(
        max(node.x for node in nodes) - min(node.x for node in nodes),
        max(node.y for node in nodes) - min(node.y for node in nodes),
    )
    return max(_PIXEL_MIN_TOLERANCE, span * _PIXEL_TOLERANCE_RATIO)


def _auto_node_type() -> MapNodeType:
    found = MapNodeType.objects.filter(name=AUTO_NODE_TYPE).first()
    if found is not None:
        return found
    color = NODE_COLORS[len(MapNodeType.objects.all()) % len(NODE_COLORS)]
    return MapNodeType.objects.create(name=AUTO_NODE_TYPE, color=color)


def collect_lines() -> tuple[dict[str, list[SourceLine]], list[SourceLine]]:
    """按「网络」收集折线：同一条路网内部才需要打断（公路↔公路、铁路↔铁路）。"""
    groups: dict[str, list[SourceLine]] = {}
    lines: list[SourceLine] = []
    for edge in MapEdge.objects.select_related('from_node', 'to_node', 'path_type').all():
        points = [(float(p[0]), float(p[1])) for p in (edge.path or [])
                  if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(points) < 2:
            points = [(edge.from_node.x, edge.from_node.y),
                      (edge.to_node.x, edge.to_node.y)]
        line = SourceLine(
            key=edge.id, points=points, path_type_id=edge.path_type_id,
            start_node=edge.from_node_id, end_node=edge.to_node_id,
        )
        lines.append(line)
        groups.setdefault(network_of(edge.path_type.name if edge.path_type else ''), []).append(line)
    return groups, lines


# 业务节点 → 它该接入的「网络」：码头接水运、车站接铁路、机场接航线、其余接公路
_FAMILY_BY_NODE_TYPE = {
    '码头': 'water',
    '火车站': 'rail',
    '机场': 'air',
    '城市点位': 'road',
    '高速口': 'road',
}


def _family_of(node: MapNode) -> str:
    return _FAMILY_BY_NODE_TYPE.get(node.node_type.name, 'road')


# 车站/码头/机场这类「属于某条线」的点位，源数据里点位图层与线图层常有十几公里的偏差，
# 所以接入半径按地图跨度放宽；城市/高速口仍用严格容差（它们离路网远近已由接驳范围覆盖）。
_STATION_FAMILIES = {'rail', 'water', 'air'}
_STATION_RADIUS_RATIO = 0.015


def _node_spurs(nodes: list[MapNode], groups: dict[str, list[SourceLine]],
                tolerance: float, span: float = 0.0) -> list[tuple[str, SourceLine]]:
    """点位节点压在线上（码头落在河道上、高速口压在公路上）时，补一条极短的接入线。

    这类节点是独立绘制出来的「点图层」，谁都没把它跟经过它的线连起来：地图上看是在线上，
    路网里却是个孤点。补一条「节点 → 线上投影点」的短线，平面化就会把那条线在该点切开，
    节点也就真正接上了。
    """
    connected: dict[str, set[int]] = {}
    for family, lines in groups.items():
        ids = connected.setdefault(family, set())
        for line in lines:
            if line.start_node is not None:
                ids.add(line.start_node)
            if line.end_node is not None:
                ids.add(line.end_node)

    station_radius = max(tolerance, span * _STATION_RADIUS_RATIO)
    cell = max(tolerance, station_radius) if tolerance > 0 else 1.0
    grids: dict[str, dict[tuple[int, int], list[tuple[SourceLine, int]]]] = {}
    for family, lines in groups.items():
        grid: dict[tuple[int, int], list[tuple[SourceLine, int]]] = {}
        for line in lines:
            for index in range(len(line.points) - 1):
                a = line.points[index]
                b = line.points[index + 1]
                for gx in range(int(min(a[0], b[0]) // cell) - 1, int(max(a[0], b[0]) // cell) + 2):
                    for gy in range(int(min(a[1], b[1]) // cell) - 1, int(max(a[1], b[1]) // cell) + 2):
                        grid.setdefault((gx, gy), []).append((line, index))
        grids[family] = grid

    spurs: list[tuple[str, SourceLine]] = []
    for node in nodes:
        family = _family_of(node)
        if family not in grids:
            continue
        if node.id in connected.get(family, set()):
            continue
        radius = station_radius if family in _STATION_FAMILIES else tolerance
        gx = int(node.x // cell)
        gy = int(node.y // cell)
        best: tuple[float, SourceLine, tuple[float, float]] | None = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for line, index in grids[family].get((gx + dx, gy + dy), ()):
                    a = line.points[index]
                    b = line.points[index + 1]
                    length_squared = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
                    if length_squared <= 0:
                        continue
                    t = ((node.x - a[0]) * (b[0] - a[0]) + (node.y - a[1]) * (b[1] - a[1])) / length_squared
                    t = max(0.0, min(1.0, t))
                    px = a[0] + (b[0] - a[0]) * t
                    py = a[1] + (b[1] - a[1]) * t
                    gap = ((node.x - px) ** 2 + (node.y - py) ** 2) ** 0.5
                    if gap > radius:
                        continue
                    if best is None or gap < best[0]:
                        best = (gap, line, (px, py))
        if best is None:
            continue
        target_point = best[2]
        if best[0] <= 1e-6:
            # 节点正好压在线上：沿线段挪一点点，避免生成零长度线（会被当成重复点丢掉）
            a = best[1].points[0]
            b = best[1].points[-1]
            dx = (b[0] - a[0]) or 1.0
            dy = (b[1] - a[1]) or 0.0
            length = (dx * dx + dy * dy) ** 0.5
            target_point = (target_point[0] + dx / length * 1e-3,
                            target_point[1] + dy / length * 1e-3)
        spurs.append((family, SourceLine(
            key=-len(spurs) - 1,
            points=[(node.x, node.y), target_point],
            path_type_id=best[1].path_type_id,
            start_node=node.id,
            end_node=None,
        )))
    return spurs


def build_plan(tolerance: float | None = None, geo: bool | None = None):
    """计算重建方案（不写库）。"""
    nodes = list(MapNode.objects.select_related('node_type').all())
    groups, lines = collect_lines()
    tol = float(tolerance) if tolerance else default_tolerance(nodes)
    # 点位节点压在线上时补接入线，先生成，再一起平面化
    span = 0.0
    if nodes:
        span = max(
            max(node.x for node in nodes) - min(node.x for node in nodes),
            max(node.y for node in nodes) - min(node.y for node in nodes),
        )
    spurs = _node_spurs(nodes, groups, tol, span)
    for family, spur in spurs:
        groups.setdefault(family, []).append(spur)
        lines.append(spur)
    # 距离口径按「坐标本身」判断，而不是 MapSettings.mode：
    # 早期 QGIS 导入会把像素坐标的工程也标成 GEO，照 mode 走会把 158 单位算成 1.5 万公里。
    if geo is None:
        geo = _looks_like_lonlat(nodes)
    return {
        'nodes': nodes,
        'lines': lines,
        'edges_count': len(lines),
        'plan': planarize_networks(groups, tolerance=tol, geo=geo,
                                   split_networks=('road', 'rail', 'water')),
        'tolerance': tol,
        'geo': geo,
        'spurs': len(spurs),
    }


def _pick_node(node_ids: list[int], by_id: dict[int, MapNode]) -> int | None:
    """一个聚类里优先保留「有业务名」的节点，其次保留 id 最小的自动节点。"""
    if not node_ids:
        return None
    named = [nid for nid in node_ids
             if nid in by_id and by_id[nid].node_type.name != AUTO_NODE_TYPE]
    pool = named or [nid for nid in node_ids if nid in by_id]
    return min(pool) if pool else None


def _cluster_regions(plan, by_line: dict[int, SourceLine],
                     by_id: dict[int, MapNode]) -> dict[str, str]:
    """给新交点节点挑一个区域：优先同簇业务节点，其次线路端点所在区域。"""
    regions: dict[str, str] = {}
    for planar_node in plan.nodes.values():
        for node_id in planar_node.node_ids:
            node = by_id.get(node_id)
            if node is not None and node.region:
                regions[planar_node.key] = node.region
                break
    for arc in plan.arcs:
        line = by_line.get(arc.line_key)
        if line is None or line.start_node is None:
            continue
        source = by_id.get(line.start_node)
        region = source.region if source is not None else ''
        if not region:
            continue
        for key in (arc.start, arc.end):
            regions.setdefault(key, region)
    return regions


@dataclass
class _Row:
    """一条待落库的边。"""

    start: str
    end: str
    points: list
    distance: float
    path_type_id: int | None


def _plan_rows(plan, by_id) -> tuple[list[_Row], int]:
    """弧段 1:1 落库：一段路对应一条边——不合并、不补点、不丢弃。

    并行路段和回环都是真实路面，`map_edges` 已放开「起终点唯一」约束，
    所以这里不需要为它们做任何取舍。
    """
    target = {key: _pick_node(node.node_ids, by_id) for key, node in plan.nodes.items()}
    rows: list[_Row] = []
    loops = 0
    for arc in plan.arcs:
        start_id = target.get(arc.start)
        end_id = target.get(arc.end)
        start = f'id{start_id}' if start_id is not None else arc.start
        end = f'id{end_id}' if end_id is not None else arc.end
        if start == end:
            loops += 1
        rows.append(_Row(start, end, arc.points, arc.length, arc.path_type_id))
    return rows, loops


def summarize(built) -> dict:
    """把重建方案折成可展示的报告（dry-run 也用它）。"""
    plan = built['plan']
    nodes = built['nodes']
    by_id = {node.id: node for node in nodes}
    merged = 0
    created = 0
    kept_ids: set[int] = set()
    for planar_node in plan.nodes.values():
        if not planar_node.node_ids:
            created += 1
            continue
        kept = _pick_node(planar_node.node_ids, by_id)
        if kept is not None:
            kept_ids.add(kept)
    for planar_node in plan.nodes.values():
        if not planar_node.node_ids:
            continue
        kept = _pick_node(planar_node.node_ids, by_id)
        # 只有「自动节点」、且没被别的聚类选中当保留节点的，才会被真正清理；
        # 统计口径要和清理一致，否则 changed 永远为 True，命令一遍遍白跑。
        merged += len([
            nid for nid in planar_node.node_ids
            if nid != kept and nid not in kept_ids and by_id.get(nid) is not None
            and by_id[nid].node_type.name == AUTO_NODE_TYPE
        ])
    rows, loops = _plan_rows(plan, by_id)
    pairs = Counter(tuple(sorted((row.start, row.end))) for row in rows)
    parallels = sum(count - 1 for count in pairs.values() if count > 1)
    changed = bool(
        plan.stats.get('intersections')
        or plan.stats.get('tJunctions')
        or merged
        or len(rows) != built['edges_count']
    )
    return {
        'changed': changed,
        'tolerance': round(built['tolerance'], 6),
        'edgesBefore': built['edges_count'],
        'edgesAfter': len(rows),
        'nodesBefore': len(nodes),
        'nodesCreated': created,
        'nodesMerged': merged,
        'nodesAfter': len(nodes) + created - merged,
        'intersections': plan.stats.get('intersections', 0),
        'tJunctions': plan.stats.get('tJunctions', 0),
        'endpointMerges': plan.stats.get('endpointMerges', 0),
        'selfLoops': loops,
        'parallelArcs': parallels,
    }


def rebuild_topology(*, apply: bool = False, tolerance: float | None = None,
                     geo: bool | None = None, max_passes: int = 4) -> dict:
    """端点吸附 + T 型接头 + 交点打断；apply=False 时只算不写。

    焊接会改变几何，从而牵动下一轮的吸附（合并后在别处又产生新交点）。单轮跑不干净，
    所以这里按「跑到没有变化」迭代，最多 ``max_passes`` 轮。dry-run 只算第一轮。
    """
    first = None
    report = None
    passes = 0
    changed = False
    applied = False
    while True:
        report = _rebuild_once(apply=apply, tolerance=tolerance, geo=geo)
        passes += 1
        changed = changed or report['changed']
        applied = applied or bool(report.get('applied'))
        if first is None:
            first = report
        if not apply or not report.get('changed') or passes >= max_passes:
            break
    report['edgesBefore'] = first['edgesBefore']
    report['nodesBefore'] = first['nodesBefore']
    report['changed'] = changed
    report['applied'] = applied
    report['passes'] = passes
    return report


def _rebuild_once(*, apply: bool, tolerance: float | None, geo: bool | None) -> dict:
    """单轮：算方案（可选写库）。"""
    built = build_plan(tolerance=tolerance, geo=geo)
    built['edges_count'] = MapEdge.objects.count()
    plan = built['plan']
    nodes = built['nodes']
    by_id = {node.id: node for node in nodes}
    by_line = {line.key: line for line in built['lines']}
    regions = _cluster_regions(plan, by_line, by_id)
    report = summarize(built)
    if not apply or not report['changed']:
        report['applied'] = False
        return report

    alias = get_competition_alias()
    node_type = _auto_node_type()
    rows, _loops = _plan_rows(plan, by_id)

    with transaction.atomic(using=alias or 'default'):
        # 1) 每个聚类选一个「保留节点」；没有旧节点的聚类新建自动节点
        target: dict[str, int] = {}
        pending: dict[str, MapNode] = {}
        for key, planar_node in plan.nodes.items():
            kept = _pick_node(planar_node.node_ids, by_id)
            if kept is not None:
                target[key] = kept
                target[f'id{kept}'] = kept
                continue
            pending[key] = MapNode(
                name=auto_node_name(planar_node.x, planar_node.y),
                region=regions.get(key, ''),
                node_type=node_type,
                x=planar_node.x, y=planar_node.y,
            )
        if pending:
            MapNode.objects.bulk_create(list(pending.values()))
            for key, node in pending.items():
                target[key] = node.id  # PostgreSQL RETURNING 会回填主键
        # 被任何聚类选为「保留节点」的 id：清理时不能删（它还被别的网络的弧段引用着）
        kept_ids = set(target.values())

        # 2) 弧段落库：一段路一条边，几何原样保留
        MapEdge.objects.all().delete()
        MapEdge.objects.bulk_create([
            MapEdge(
                from_node_id=target[row.start], to_node_id=target[row.end],
                distance=round(row.distance, 3),
                path=[[round(p[0], 7), round(p[1], 7)] for p in row.points],
                path_type_id=row.path_type_id,
            )
            for row in rows
        ])

        # 3) 清理被并掉、且不再被任何边引用的自动节点（业务节点永不删除）
        # 同一个节点可能同时出现在两个网络的聚类里，用 id 去重并走 queryset 删除，
        # 避免对同一个对象 delete 两次（第二次会因为 pk 已被清空而报错）。
        removed = 0
        seen_deleted: set[int] = set()
        for planar_node in plan.nodes.values():
            kept = target.get(planar_node.key)
            for node_id in planar_node.node_ids:
                if node_id == kept or node_id in seen_deleted:
                    continue
                node = by_id.get(node_id)
                if node is None or node.node_type.name != AUTO_NODE_TYPE:
                    continue
                if node_id in kept_ids:
                    continue
                if MapEdge.objects.filter(from_node_id=node_id).exists() \
                        or MapEdge.objects.filter(to_node_id=node_id).exists():
                    continue
                seen_deleted.add(node_id)
                MapNode.objects.filter(pk=node_id).delete()
                removed += 1

    report.update({
        'applied': True,
        'nodesRemoved': removed,
        'importedAt': timezone.now().isoformat(),
    })
    return report
