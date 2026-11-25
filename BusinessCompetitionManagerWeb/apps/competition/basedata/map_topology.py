"""路网平面化：端点吸附 + T 型接头 + 交点打断。

导入的线图层通常只是「一堆互相压盖的折线」：它们视觉上交叉，但彼此不共享端点，
QGIS/Shapefile 也不会替我们打断。前端导航此前只能靠 20×15 网格把相近的采样点硬凑成
同一个顶点——既不准也不稳定（里程会缩水、路线会跳线）。

这里按经典 GIS 做法把线路变成真正的「节点—弧段」图：

1. **交点打断**：两条线真正相交（含同一条线自交）时，在交点处把两条线都切开；
2. **T 型接头**：某条线的端点落在另一条线内部（距离 ≤ 容差）时，把后者在投影处切开；
3. **端点吸附**：距离 ≤ 容差的所有端点并成同一个节点；同一 MapNode 的端点必然合并。

输出只是「新图应该长什么样」（节点坐标 + 弧段 + 归属的原节点 id），落库由
``map_rebuild`` 负责——算法本身不依赖 Django，可以单独单测。
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .map_geometry import (
    Point,
    drop_repeated_points,
    haversine_km,
    lerp,
    segment_intersection,
    segment_projection,
)

# 交点必须落在两条线段的「内部」才算打断（端点相接交给端点吸附处理）
_T_EPS = 1e-9
# 参数空间上两个切点足够近时视为同一个点
_CUT_EPS = 1e-12
# 小于该长度的弧段没有意义（容差量级以下），直接丢弃
_MIN_ARC_RATIO = 1e-6
# 内部顶点「压在另一条路上」时，两条线夹角小于 ~20° 视为并行，不算路口
_PARALLEL_SIN = 0.34


@dataclass
class SourceLine:
    """待打断的一条线（导入的线要素 / 现有 MapEdge）。"""

    key: int
    points: list[Point]
    path_type_id: int | None = None
    start_node: int | None = None
    end_node: int | None = None


@dataclass
class PlanarNode:
    """平面化后的一个节点：坐标 + 归并进来的原 MapNode id。"""

    key: str
    x: float
    y: float
    node_ids: list[int] = field(default_factory=list)


@dataclass
class PlanarArc:
    """平面化后的一段弧：两个节点之间的一段折线。"""

    line_key: int
    path_type_id: int | None
    points: list[Point]
    start: str
    end: str
    length: float


@dataclass
class PlanarResult:
    nodes: dict[str, PlanarNode]
    arcs: list[PlanarArc]
    stats: dict


@dataclass
class _BreakPoint:
    """线路上的一个「切点」：端点或交点/投影点。"""

    point: Point
    index: int
    node_id: int | None = None
    is_endpoint: bool = False
    line_index: int = -1
    which: int = -1
    stop: tuple[int, float] | None = None


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _cell_key(x: float, y: float, cell: float) -> tuple[int, int]:
    return (int(math.floor(x / cell)), int(math.floor(y / cell)))


def _union_find(size: int):
    parent = list(range(size))
    merges = [0]

    def find(item: int) -> int:
        root = item
        while parent[root] != root:
            root = parent[root]
        while parent[item] != root:
            parent[item], item = root, parent[item]
        return root

    def union(left: int, right: int) -> bool:
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            return False
        parent[root_left] = root_right
        merges[0] += 1
        return True

    return find, union, merges


def _segment_grid(points_by_line: list[list[Point]], cell: float) -> list[list[int]]:
    """把所有线段按网格分桶，返回 (线段下标 -> 命中格子列表)。"""
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    index = 0
    for points in points_by_line:
        for seg_index in range(len(points) - 1):
            a, b = points[seg_index], points[seg_index + 1]
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for gx in range(int(math.floor(x0 / cell)), int(math.floor(x1 / cell)) + 1):
                for gy in range(int(math.floor(y0 / cell)), int(math.floor(y1 / cell)) + 1):
                    grid[(gx, gy)].append(index)
            index += 1
    return grid


def _stop_point(points: list[Point], stop: tuple[int, float]) -> Point:
    seg_index, t = stop
    if t <= 0:
        return points[seg_index]
    if t >= 1:
        return points[seg_index + 1]
    return lerp(points[seg_index], points[seg_index + 1], t)


def _same_point(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) <= 1e-12 and abs(a[1] - b[1]) <= 1e-12


def _slice_points(points: list[Point], start: tuple[int, float],
                  end: tuple[int, float]) -> list[Point]:
    """按 (线段下标, t) 切出两点之间的折线（含两端精确坐标）。"""
    start_seg = start[0]
    end_seg = end[0]
    out: list[Point] = [_stop_point(points, start)]
    for index in range(start_seg + 1, end_seg + 1):
        out.append(points[index])
    out.append(_stop_point(points, end))
    cleaned: list[Point] = []
    for point in out:
        if cleaned and _same_point(cleaned[-1], point):
            continue
        cleaned.append(point)
    return cleaned


def _coord_length(a: Point, b: Point) -> float:
    """坐标平面上的长度（网格/容差判断用，单位与坐标一致）。"""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _geo_length(a: Point, b: Point) -> float:
    return haversine_km(a, b)


def planarize(lines: list[SourceLine], *, tolerance: float, geo: bool = False) -> PlanarResult:
    """把折线集合变成节点-弧段图（端点吸附 + T 型接头 + 交点打断）。

    ``geo=True`` 时坐标是经纬度，弧长按球面距离（km）计算；否则按平面欧氏（1 单位≈1km）。
    容差始终是「坐标单位」：像素地图是单位，经纬度地图是度。
    """
    if tolerance <= 0:
        raise ValueError('tolerance 必须为正数')
    measure = _geo_length if geo else _coord_length

    prepared: list[SourceLine] = []
    for line in lines:
        points = drop_repeated_points(line.points)
        if len(points) < 2:
            continue
        prepared.append(SourceLine(
            key=line.key, points=points, path_type_id=line.path_type_id,
            start_node=line.start_node, end_node=line.end_node,
        ))
    empty_stats = {
        'lines': 0, 'segments': 0, 'intersections': 0, 'tJunctions': 0,
        'endpointMerges': 0, 'nodeMerges': 0, 'nodes': 0, 'arcs': 0,
        'selfLoops': 0, 'tolerance': tolerance,
    }
    if not prepared:
        return PlanarResult(nodes={}, arcs=[], stats=empty_stats)

    points_by_line = [line.points for line in prepared]
    all_points = [point for points in points_by_line for point in points]
    segment_lengths = [
        _coord_length(points[i], points[i + 1])
        for points in points_by_line for i in range(len(points) - 1)
    ]
    span = max(
        max(p[0] for p in all_points) - min(p[0] for p in all_points),
        max(p[1] for p in all_points) - min(p[1] for p in all_points),
    )
    # 网格只用于加速：既要装得下容差范围，也不能让长线段铺满太多格子
    cell = max(tolerance, _median(segment_lengths) if segment_lengths else 0.0,
               span / 400 if span > 0 else tolerance)
    grid = _segment_grid(points_by_line, cell)
    segment_refs = [
        (line_index, seg_index)
        for line_index, points in enumerate(points_by_line)
        for seg_index in range(len(points) - 1)
    ]

    # ---------------- 1) 交点打断 ----------------
    segment_count = len(segment_refs)
    candidate_codes: set[int] = set()
    for bucket in grid.values():
        if len(bucket) < 2:
            continue
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                low, high = bucket[i], bucket[j]
                if low > high:
                    low, high = high, low
                candidate_codes.add(low * segment_count + high)

    cuts: dict[tuple[int, int], set[float]] = defaultdict(set)
    intersection_count = 0
    for code in candidate_codes:
        first, second = divmod(code, segment_count)
        line_a, seg_a = segment_refs[first]
        line_b, seg_b = segment_refs[second]
        if line_a == line_b and abs(seg_a - seg_b) <= 1:
            continue  # 同一条线的相邻线段：共享端点，不算相交
        pa, pa_next = points_by_line[line_a][seg_a], points_by_line[line_a][seg_a + 1]
        pb, pb_next = points_by_line[line_b][seg_b], points_by_line[line_b][seg_b + 1]
        hit = segment_intersection(pa, pa_next, pb, pb_next)
        if hit is None:
            continue
        t, u = hit
        if not (_T_EPS < t < 1 - _T_EPS and _T_EPS < u < 1 - _T_EPS):
            continue
        cuts[(line_a, seg_a)].add(t)
        cuts[(line_b, seg_b)].add(u)
        intersection_count += 1

    # ---------------- 2) 端点吸附 + T 型接头 ----------------
    endpoints: list[tuple[int, int]] = []   # (line_index, 0=起点 / 1=终点)
    endpoint_points: list[Point] = []
    for line_index, points in enumerate(points_by_line):
        endpoints.append((line_index, 0))
        endpoint_points.append(points[0])
        endpoints.append((line_index, 1))
        endpoint_points.append(points[-1])

    find_endpoint, union_endpoint, endpoint_merges = _union_find(len(endpoints))
    geometric_endpoint_merges = 0

    endpoint_grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, point in enumerate(endpoint_points):
        endpoint_grid[_cell_key(point[0], point[1], tolerance)].append(index)
    for index, point in enumerate(endpoint_points):
        gx, gy = _cell_key(point[0], point[1], tolerance)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in endpoint_grid.get((gx + dx, gy + dy), ()):
                    if other <= index:
                        continue
                    op = endpoint_points[other]
                    if math.hypot(op[0] - point[0], op[1] - point[1]) <= tolerance:
                        if union_endpoint(index, other):
                            geometric_endpoint_merges += 1

    # 2b) 焊接：同一组端点统一到同一个坐标。
    #     只靠「容差内算一个节点」是不够的——相邻顶点也会被同一容差吸进去，
    #     整段路被压缩成自环。焊成精确同一点后，聚类可以用很小的阈值。
    representative: dict[int, int] = {}
    for index, (line_index, which) in enumerate(endpoints):
        root = find_endpoint(index)
        node_id = (prepared[line_index].start_node if which == 0
                   else prepared[line_index].end_node)
        current = representative.get(root)
        if current is not None:
            current_line, current_which = endpoints[current]
            current_node = (prepared[current_line].start_node if current_which == 0
                            else prepared[current_line].end_node)
            if current_node is not None or node_id is None:
                continue
        representative[root] = index
    for index, (line_index, which) in enumerate(endpoints):
        welded = endpoint_points[representative[find_endpoint(index)]]
        endpoint_points[index] = welded
        if which == 0:
            points_by_line[line_index][0] = welded
        else:
            points_by_line[line_index][-1] = welded

    # 端点落在别的线内部（T 型接头）：在后者上插切点，并把端点焊到投影点
    t_junction_count = 0
    for index, point in enumerate(endpoint_points):
        line_index, _which = endpoints[index]
        gx, gy = _cell_key(point[0], point[1], cell)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for segment_index in grid.get((gx + dx, gy + dy), ()):
                    other_line, other_seg = segment_refs[segment_index]
                    if other_line == line_index:
                        continue
                    a = points_by_line[other_line][other_seg]
                    b = points_by_line[other_line][other_seg + 1]
                    t, gap = segment_projection(point, a, b)
                    if gap > tolerance or not (_T_EPS < t < 1 - _T_EPS):
                        continue
                    # 端点本来就贴着这条线段的某个端点（同一个顶点）时不切：
                    # 那是端点吸附的活儿，重复切会把同一处越切越碎
                    if min(math.hypot(point[0] - a[0], point[1] - a[1]),
                           math.hypot(point[0] - b[0], point[1] - b[1])) <= tolerance:
                        continue
                    if best is None or gap < best[0]:
                        best = (gap, other_line, other_seg, t)
        if best is None:
            continue
        _, other_line, other_seg, t = best
        projection = lerp(points_by_line[other_line][other_seg],
                          points_by_line[other_line][other_seg + 1], t)
        line_index, which = endpoints[index]
        endpoint_points[index] = projection
        if which == 0:
            points_by_line[line_index][0] = projection
        else:
            points_by_line[line_index][-1] = projection
        cuts[(other_line, other_seg)].add(t)
        t_junction_count += 1

    # 2c) 顶点吸附：线的**内部顶点**压在另一条线上时，两边都要打断。
    # 路网常按折线顶点对齐绘制，交叉点恰好落在某条线的内部顶点上：只判「线段真交叉」
    # 会漏掉它们（这张图实测漏了 529 处），前端因此绕远路。
    vertex_junction_count = 0
    for line_index, points in enumerate(points_by_line):
        for vertex_index in range(1, len(points) - 1):
            point = points[vertex_index]
            gx, gy = _cell_key(point[0], point[1], cell)
            before = points[vertex_index - 1]
            after = points[vertex_index + 1]
            vx, vy = after[0] - before[0], after[1] - before[1]
            v_len = math.hypot(vx, vy)
            best_vertex = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for segment_index in grid.get((gx + dx, gy + dy), ()):
                        other_line, other_seg = segment_refs[segment_index]
                        if other_line == line_index:
                            continue
                        a = points_by_line[other_line][other_seg]
                        b = points_by_line[other_line][other_seg + 1]
                        t, gap = segment_projection(point, a, b)
                        if gap > tolerance:
                            continue
                        # 走向几乎一致的是「平行且靠得近」，不是路口：
                        # 不做这个过滤会把长距离并行段切成上千个假路口
                        sx, sy = b[0] - a[0], b[1] - a[1]
                        s_len = math.hypot(sx, sy)
                        if v_len > 0 and s_len > 0:
                            sin_angle = abs(vx * sy - vy * sx) / (v_len * s_len)
                            if sin_angle < _PARALLEL_SIN:
                                continue
                        if best_vertex is None or gap < best_vertex[0]:
                            best_vertex = (gap, other_line, other_seg, t)
            if best_vertex is None:
                continue
            _, other_line, other_seg, t = best_vertex
            projection = lerp(points_by_line[other_line][other_seg],
                              points_by_line[other_line][other_seg + 1], t)
            points_by_line[line_index][vertex_index] = projection
            if t <= _T_EPS:
                if other_seg > 0:
                    cuts[(other_line, other_seg - 1)].add(1.0)
            elif t >= 1 - _T_EPS:
                cuts[(other_line, other_seg)].add(1.0)
            else:
                cuts[(other_line, other_seg)].add(t)
            # 自己这条线也要在该顶点处断开，否则接不上对方切出来的节点
            cuts[(line_index, vertex_index - 1)].add(1.0)
            vertex_junction_count += 1

    # ---------------- 3) 切点聚类成节点 ----------------
    break_points: list[_BreakPoint] = []
    endpoint_break: dict[int, _BreakPoint] = {}
    for index, (line_index, which) in enumerate(endpoints):
        node_id = (prepared[line_index].start_node if which == 0
                   else prepared[line_index].end_node)
        record = _BreakPoint(
            point=endpoint_points[index], index=len(break_points), node_id=node_id,
            is_endpoint=True, line_index=line_index, which=which,
        )
        break_points.append(record)
        endpoint_break[index] = record

    cut_break: dict[tuple[int, int, float], _BreakPoint] = {}
    for (line_index, seg_index), values in cuts.items():
        for t in sorted(values):
            record = _BreakPoint(
                point=lerp(points_by_line[line_index][seg_index],
                           points_by_line[line_index][seg_index + 1], t),
                index=len(break_points), line_index=line_index, stop=(seg_index, t),
            )
            break_points.append(record)
            cut_break[(line_index, seg_index, t)] = record

    find_break, union_break, break_merges = _union_find(len(break_points))

    # 合并前的合法性检查：同一条线上「紧挨着」的两个切点不能被（哪怕是间接地）并进
    # 同一个节点——那会把两点之间那一小段路缩成自环，路段在导航里直接失效，
    # 还会把相邻的几个路口粘成一团。
    cluster_members: dict[int, list[int]] = {i: [i] for i in range(len(break_points))}

    def collapses_line(left_index: int, right_index: int) -> bool:
        """同一条线上的两个**不同位置**不能并成一个节点。

        并了就会把两点之间那段路缩成自环（回环），路段在导航里直接失效。
        只有「几乎完全重合」的情况放行：自交回到同一点、首尾相接的闭环。
        """
        left = break_points[left_index]
        right = break_points[right_index]
        if left.line_index < 0 or left.line_index != right.line_index:
            return False
        gap = math.hypot(right.point[0] - left.point[0], right.point[1] - left.point[1])
        return gap > 1e-6

    def merge_breaks(left: int, right: int) -> bool:
        left_root, right_root = find_break(left), find_break(right)
        if left_root == right_root:
            return False
        for a in cluster_members.get(left_root, ()):
            for b in cluster_members.get(right_root, ()):
                if collapses_line(a, b):
                    return False
        if not union_break(left, right):
            return False
        merged_root = find_break(left)
        members = cluster_members.get(left_root, []) + cluster_members.get(right_root, [])
        # 先摘掉两个旧 root 再挂到新 root 上：merged_root 可能就是其中一个旧 root，
        # 顺序反了会把刚合并的成员表删掉，后面的检查就全部失效
        cluster_members.pop(left_root, None)
        cluster_members.pop(right_root, None)
        cluster_members[merged_root] = members
        return True

    # 3a) 同一 MapNode 的端点必须合并（几何偏差不应把它们拆成两个节点）
    break_by_node: dict[int, list[int]] = defaultdict(list)
    for record in endpoint_break.values():
        if record.node_id is not None:
            break_by_node[record.node_id].append(record.index)
    for indices in break_by_node.values():
        for other in indices[1:]:
            merge_breaks(indices[0], other)

    # 3b) 容差内的切点合并
    # 几何已经焊接过，这里只合并「精确重合」的点（1e-6 量级）：
    # 用容差当聚类半径会把相距一两公里的相邻路口也粘在一起。
    merge_eps = 1e-6
    break_grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for record in break_points:
        break_grid[_cell_key(record.point[0], record.point[1], tolerance)].append(record.index)
    for record in break_points:
        gx, gy = _cell_key(record.point[0], record.point[1], tolerance)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other_index in break_grid.get((gx + dx, gy + dy), ()):
                    if other_index <= record.index:
                        continue
                    other = break_points[other_index]
                    if math.hypot(other.point[0] - record.point[0],
                                  other.point[1] - record.point[1]) > merge_eps:
                        continue
                    merge_breaks(record.index, other_index)

    # ---------------- 4) 组装节点 ----------------
    nodes: dict[str, PlanarNode] = {}
    root_position: dict[int, tuple[Point, int]] = {}
    root_node_ids: dict[int, list[int]] = defaultdict(list)
    for record in break_points:
        root = find_break(record.index)
        if record.node_id is not None:
            root_node_ids[root].append(record.node_id)
        # 坐标优先级：带业务节点的端点 > 普通端点 > 交点
        score = 0 if record.node_id is not None else (1 if record.is_endpoint else 2)
        current = root_position.get(root)
        if current is None or score < current[1]:
            root_position[root] = (record.point, score)
    for root, (point, _score) in root_position.items():
        nodes[f'n{root}'] = PlanarNode(
            key=f'n{root}', x=point[0], y=point[1],
            node_ids=sorted(set(root_node_ids.get(root, []))),
        )

    def node_key(record: _BreakPoint | None) -> str | None:
        if record is None:
            return None
        return f'n{find_break(record.index)}'

    # ---------------- 5) 逐条线切出弧段 ----------------
    arcs: list[PlanarArc] = []
    for line_index, line in enumerate(prepared):
        points = points_by_line[line_index]
        last_seg = len(points) - 2
        stops: list[tuple[tuple[int, float], _BreakPoint | None]] = [
            ((0, 0.0), endpoint_break[line_index * 2]),
        ]
        for seg_index in range(len(points) - 1):
            for t in sorted(cuts.get((line_index, seg_index), ())):
                if t <= _CUT_EPS:
                    continue
                stops.append(((seg_index, t), cut_break.get((line_index, seg_index, t))))
        stops.append(((last_seg, 1.0), endpoint_break[line_index * 2 + 1]))

        deduped: list[tuple[tuple[int, float], _BreakPoint | None]] = []
        for stop, record in stops:
            # 只合并「参数位置相同」的切点（相邻线段交界的 t=1 / t=0）。
            # 注意不能按坐标判重：自交回到同一点的线（8 字型）会有两个真实切点，
            # 按坐标去重会把中间那段回环整段吞掉。
            if deduped and abs((stop[0] + stop[1]) - (deduped[-1][0][0] + deduped[-1][0][1])) <= 1e-9:
                if deduped[-1][1] is None and record is not None:
                    deduped[-1] = (deduped[-1][0], record)
                continue
            deduped.append((stop, record))

        min_coord_length = tolerance * _MIN_ARC_RATIO
        for i in range(len(deduped) - 1):
            start_stop, start_record = deduped[i]
            end_stop, end_record = deduped[i + 1]
            start_key = node_key(start_record)
            end_key = node_key(end_record)
            if start_key is None or end_key is None:
                continue
            arc_points = _slice_points(points, start_stop, end_stop)
            if len(arc_points) < 2:
                continue
            coord_length = sum(_coord_length(arc_points[k], arc_points[k + 1])
                               for k in range(len(arc_points) - 1))
            # 切点被容差并掉后留下的碎段直接丢弃；真正的回环（起点终点同节点）
            # 保留几何（否则地图上会缺一段路），导航侧会忽略它
            if coord_length <= min_coord_length:
                continue
            arcs.append(PlanarArc(
                line_key=line.key, path_type_id=line.path_type_id, points=arc_points,
                start=start_key, end=end_key,
                length=sum(measure(arc_points[k], arc_points[k + 1])
                           for k in range(len(arc_points) - 1)),
            ))

    # 注意：这里**不**按节点对去重。并行弧段（两条路连同一对节点）和回环（起点=终点）
    # 都是真实路面，丢掉就等于从地图上抹掉一段路；落库时由 map_rebuild 在中点补一个
    # 节点把它们切开放进去，几何一段都不丢。

    stats = dict(empty_stats)
    stats.update({
        'lines': len(prepared),
        'segments': segment_count,
        'intersections': intersection_count,
        'tJunctions': t_junction_count,
        'vertexJunctions': vertex_junction_count,
        'endpointMerges': geometric_endpoint_merges,
        'nodeMerges': break_merges[0],
        'nodes': len(nodes),
        'arcs': len(arcs),
        'selfLoops': sum(1 for arc in arcs if arc.start == arc.end),
    })
    return PlanarResult(nodes=nodes, arcs=arcs, stats=stats)


def network_of(path_type_name: str) -> str:
    """把路径类型归到「网络」：只有同一网络内部才需要打断。

    公路在交叉口是真的路口，要打断；航空线/水路线只在机场/码头起降，
    被公路穿过并不构成换乘点——按网络分开平面化，避免把航线切成几百段、
    顺便造出一堆「路边就能上飞机」的假换乘点。
    """
    name = path_type_name or ''
    if '航空' in name:
        return 'air'
    if '水' in name:
        return 'water'
    if '铁路' in name:
        return 'rail'
    return 'road'


def _whole_lines(lines: list[SourceLine], prefix: str, measure) -> tuple[dict, list]:
    """不打断的网络（航空/水路）：一条线就是一整条弧，只把端点挂到节点上。"""
    nodes: dict[str, PlanarNode] = {}
    by_node: dict[int, str] = {}
    by_point: dict[tuple[float, float], str] = {}

    def key_for(point: Point, node_id: int | None) -> str:
        if node_id is not None:
            key = by_node.get(node_id)
            if key is None:
                key = f'{prefix}id{node_id}'
                by_node[node_id] = key
                nodes[key] = PlanarNode(key=key, x=point[0], y=point[1], node_ids=[node_id])
            return key
        rounded = (round(point[0], 7), round(point[1], 7))
        key = by_point.get(rounded)
        if key is None:
            key = f'{prefix}p{len(by_point)}'
            by_point[rounded] = key
            nodes[key] = PlanarNode(key=key, x=point[0], y=point[1])
        return key

    arcs: list[PlanarArc] = []
    for line in lines:
        points = drop_repeated_points(line.points)
        if len(points) < 2:
            continue
        start = key_for(points[0], line.start_node)
        end = key_for(points[-1], line.end_node)
        if start == end:
            continue
        arcs.append(PlanarArc(
            line_key=line.key, path_type_id=line.path_type_id, points=points,
            start=start, end=end,
            length=sum(measure(points[i], points[i + 1]) for i in range(len(points) - 1)),
        ))
    return nodes, arcs


def planarize_networks(groups: dict[str, list[SourceLine]], *, tolerance: float,
                       geo: bool = False,
                       split_networks: tuple[str, ...] = ('road', 'rail')) -> PlanarResult:
    """按网络分别处理再合并。

    公路/铁路这类「交叉即路口」的网络做平面化（端点吸附 + T 型接头 + 交点打断）；
    航空/水路只在机场/码头起降，被别的线穿过并不构成换乘点，整条保留，
    否则航线会被切成上千段，还会造出「空中/路中间随便换乘」的假节点。
    """
    measure = _geo_length if geo else _coord_length
    merged_nodes: dict[str, PlanarNode] = {}
    merged_arcs: list[PlanarArc] = []
    totals: dict[str, float] = {}
    summary: dict[str, int] = {}
    for network, lines in groups.items():
        if not lines:
            continue
        prefix = f'{network}:'
        if network in split_networks:
            result = planarize(lines, tolerance=tolerance, geo=geo)
            mapped: dict[str, str] = {}
            for key, node in result.nodes.items():
                new_key = prefix + key
                mapped[key] = new_key
                merged_nodes[new_key] = PlanarNode(
                    key=new_key, x=node.x, y=node.y, node_ids=list(node.node_ids))
            for arc in result.arcs:
                merged_arcs.append(PlanarArc(
                    line_key=arc.line_key, path_type_id=arc.path_type_id, points=arc.points,
                    start=mapped[arc.start], end=mapped[arc.end], length=arc.length))
            for key, value in result.stats.items():
                if isinstance(value, (int, float)):
                    totals[key] = totals.get(key, 0) + value
        else:
            nodes, arcs = _whole_lines(lines, prefix, measure)
            merged_nodes.update(nodes)
            merged_arcs.extend(arcs)
        summary[network] = len(lines)
    stats = {
        'lines': int(totals.get('lines', 0)) + sum(
            len(lines) for network, lines in groups.items() if network not in split_networks),
        'segments': int(totals.get('segments', 0)),
        'intersections': int(totals.get('intersections', 0)),
        'tJunctions': int(totals.get('tJunctions', 0)),
        'vertexJunctions': int(totals.get('vertexJunctions', 0)),
        'endpointMerges': int(totals.get('endpointMerges', 0)),
        'nodeMerges': int(totals.get('nodeMerges', 0)),
        'selfLoops': int(totals.get('selfLoops', 0)),
        'nodes': len(merged_nodes),
        'arcs': len(merged_arcs),
        'tolerance': tolerance,
        'networks': summary,
    }
    return PlanarResult(nodes=merged_nodes, arcs=merged_arcs, stats=stats)
