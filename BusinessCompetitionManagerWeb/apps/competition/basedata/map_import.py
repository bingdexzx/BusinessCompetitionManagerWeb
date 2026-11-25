"""QGIS GeoJSON 地图导入（点→节点、线→边、面→区域）。

约定（QGIS「导出 → 要素另存为 → GeoJSON，CRS 选 EPSG:4326」）：
- **点要素** → 地图节点；`properties.name`（或 `名称`）为节点名，
  `nodeType`（`节点类型`）为节点类型（缺省「默认节点」），`region`（`区域`）为所属区域。
- **线要素** → 地图边；首尾坐标为端点，自动建点/复用同名节点；
  距离优先 `properties.distance`（`距离`），否则按经纬度球面距离（km）。
- **面要素** → 区域；`properties.name`（`名称`）为区域名，
  面内节点自动归入该区域（已显式指定区域的不覆盖）。

导入成功后写 `MapSettings(mode='GEO', bounds=整体经纬度范围, regions=区域环)`，
前端据此把经纬度等比投影到画布渲染。
"""

import json
import math

from django.db import transaction
from django.utils import timezone

from apps.competition.basedata.models import (
    MapEdge, MapNode, MapNodeType, MapSettings, PathType,
)

DEFAULT_NODE_TYPE = '默认节点'
DEFAULT_PATH_TYPE = '默认道路'
NODE_COLORS = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399', '#9B59B6', '#00BCD4']
PATH_COLORS = ['#67C23A', '#409EFF', '#E6A23C', '#F56C6C', '#909399']

_NAME_KEYS = ('name', 'Name', 'NAME', '名称')
_NODE_TYPE_KEYS = ('nodeType', 'node_type', 'NodeType', '节点类型')
_PATH_TYPE_KEYS = ('pathType', 'path_type', 'PathType', '路径类型')
_REGION_KEYS = ('region', 'Region', '区域')
_DISTANCE_KEYS = ('distance', 'Distance', '距离')
_FROM_KEYS = ('from', 'fromName', '起点')
_TO_KEYS = ('to', 'toName', '终点')


class GeoJSONError(ValueError):
    """导入数据不合法（视图返回 400）。"""


def _as_text(payload):
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8-sig')
    return payload


def _as_json(payload):
    text = _as_text(payload)
    if isinstance(text, str):
        try:
            return json.loads(text)
        except ValueError as exc:
            raise GeoJSONError(f'GeoJSON 解析失败：{exc}') from exc
    return payload


def _prop(props, keys, default=''):
    for key in keys:
        value = (props or {}).get(key)
        if value not in (None, ''):
            return value
    return default


def _coord(value):
    """校验并返回 [lon, lat] 浮点对。"""
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise GeoJSONError(f'坐标非法：{value!r}')
    try:
        lon, lat = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise GeoJSONError(f'坐标非法：{value!r}') from exc
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise GeoJSONError(
            f'坐标 ({lon}, {lat}) 超出经纬度范围——请在 QGIS 导出时把 CRS 设为 EPSG:4326')
    return lon, lat


def _ring_coords(ring):
    return [_coord(p) for p in (ring or [])]


def collect(payload):
    """解析 GeoJSON → (points, lines, polygons)。

    points:   [(lon, lat, props)]
    lines:    [([lon, lat] 首点, [lon, lat] 末点, props, 全段坐标)]
    polygons: [{"name": str, "rings": [[[lon,lat], ...], ...]}]
    """
    data = _as_json(payload)
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection':
        raise GeoJSONError('需要 QGIS 导出的 GeoJSON（FeatureCollection）')
    features = data.get('features') or []
    if not features:
        raise GeoJSONError('GeoJSON 中没有要素（features 为空）')

    points, lines, polygons = [], [], []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get('geometry') or {}
        props = feature.get('properties') or {}
        gtype = geometry.get('type')
        coords = geometry.get('coordinates')

        if gtype == 'Point':
            lon, lat = _coord(coords)
            points.append((lon, lat, props))
        elif gtype == 'MultiPoint':
            for point in coords or []:
                lon, lat = _coord(point)
                points.append((lon, lat, props))
        elif gtype == 'LineString':
            path = _ring_coords(coords)
            if len(path) >= 2:
                lines.append((path[0], path[-1], props, path))
        elif gtype == 'MultiLineString':
            for part in coords or []:
                path = _ring_coords(part)
                if len(path) >= 2:
                    lines.append((path[0], path[-1], props, path))
        elif gtype == 'Polygon':
            rings = [_ring_coords(ring) for ring in (coords or []) if ring]
            rings = [ring for ring in rings if len(ring) >= 3]
            if rings:
                polygons.append({'name': str(_prop(props, _NAME_KEYS, '')), 'rings': rings})
        elif gtype == 'MultiPolygon':
            rings = []
            for polygon in coords or []:
                for ring in polygon or []:
                    ring = _ring_coords(ring)
                    if len(ring) >= 3:
                        rings.append(ring)
            if rings:
                polygons.append({'name': str(_prop(props, _NAME_KEYS, '')), 'rings': rings})
    return points, lines, polygons


def haversine_km(a, b):
    """两点经纬度球面距离（km）。"""
    lon1, lat1 = a
    lon2, lat2 = b
    radius = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 2 * radius * math.asin(math.sqrt(min(1.0, h)))


def distance_between(a, b):
    """地理坐标用球面距离；非经纬度的平面地图坐标用欧氏距离（1 单位≈1km）。"""
    if (-180 <= a[0] <= 180 and -90 <= a[1] <= 90
            and -180 <= b[0] <= 180 and -90 <= b[1] <= 90):
        return haversine_km(a, b)
    return math.hypot(b[0] - a[0], b[1] - a[1])


def point_in_ring(lon, lat, ring):
    """射线法判断点是否在多边形环内（环为 [lon, lat] 列表，不要求闭合）。"""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat):
            cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < cross:
                inside = not inside
        j = i
    return inside


class _Importer:
    """一次导入的上下文（节点/类型缓存 + 计数）。"""

    def __init__(self):
        self.nodes = {node.name: node for node in MapNode.objects.all()}
        self.by_coord = {}
        for node in self.nodes.values():
            self.by_coord[self._coord_key(node.x, node.y)] = node
        self.node_types = {t.name: t for t in MapNodeType.objects.all()}
        self.path_types = {t.name: t for t in PathType.objects.all()}
        self.explicit_regions = set()
        self.report = {
            'nodesCreated': 0, 'nodesReused': 0,
            'edgesCreated': 0, 'edgesSkipped': 0,
            'nodeTypesCreated': 0, 'pathTypesCreated': 0,
            'regions': 0,
        }

    @staticmethod
    def _coord_key(lon, lat):
        return (round(float(lon), 7), round(float(lat), 7))

    def node_type(self, name):
        name = str(name or '').strip() or DEFAULT_NODE_TYPE
        found = self.node_types.get(name)
        if found:
            return found
        color = NODE_COLORS[len(self.node_types) % len(NODE_COLORS)]
        found = MapNodeType.objects.create(name=name, color=color)
        self.node_types[name] = found
        self.report['nodeTypesCreated'] += 1
        return found

    def path_type(self, name):
        name = str(name or '').strip() or DEFAULT_PATH_TYPE
        found = self.path_types.get(name)
        if found:
            return found
        color = PATH_COLORS[len(self.path_types) % len(PATH_COLORS)]
        found = PathType.objects.create(name=name, color=color)
        self.path_types[name] = found
        self.report['pathTypesCreated'] += 1
        return found

    def unique_node_name(self, base):
        base = str(base or '').strip() or '节点'
        if base not in self.nodes:
            return base
        index = 2
        while f'{base}-{index}' in self.nodes:
            index += 1
        return f'{base}-{index}'

    def node_at(self, lon, lat, name='', node_type='', region='', unique_name=True, reuse_coord=True):
        """坐标就近复用节点；否则用 name 新建（默认重名自动加序号）。"""
        key = self._coord_key(lon, lat)
        existing = self.by_coord.get(key) if reuse_coord else None
        if existing is not None:
            self.report['nodesReused'] += 1
            return existing
        name = self.unique_node_name(name) if unique_name else (str(name or '').strip() or '节点')
        node = MapNode.objects.create(
            name=name, region=str(region or ''), node_type=self.node_type(node_type),
            x=lon, y=lat,
        )
        self.nodes[name] = node
        self.by_coord[key] = node
        self.report['nodesCreated'] += 1
        return node

    def edge(self, start, end, props, path=None):
        node_a = self.node_at(start[0], start[1], _prop(props, _FROM_KEYS, '') or self._auto_name(start))
        node_b = self.node_at(end[0], end[1], _prop(props, _TO_KEYS, '') or self._auto_name(end))
        if node_a.id == node_b.id:
            self.report['edgesSkipped'] += 1
            return None, None
        raw_distance = _prop(props, _DISTANCE_KEYS, None)
        try:
            distance = float(raw_distance)
        except (TypeError, ValueError):
            points = path or [start, end]
            distance = sum(
                distance_between(points[i], points[i + 1]) for i in range(len(points) - 1)
            )
        # 同一对节点之间允许多条边（并行路段），所以只跳过「同类型 + 同长度」的重复要素，
        # 这样重复导入同一个文件仍然幂等，但不会把真正的并行路吞掉。
        path_type = self.path_type(_prop(props, _PATH_TYPE_KEYS, ''))
        rounded = round(distance, 3)
        duplicated = False
        for a, b in ((node_a, node_b), (node_b, node_a)):
            if MapEdge.objects.filter(from_node=a, to_node=b, path_type=path_type,
                                      distance__range=(rounded - 0.001, rounded + 0.001)).exists():
                duplicated = True
                break
        if duplicated:
            self.report['edgesSkipped'] += 1
            return node_a, node_b
        MapEdge.objects.create(
            from_node=node_a, to_node=node_b,
            distance=round(distance, 3), path_type=path_type,
            path=path or [start, end],
        )
        self.report['edgesCreated'] += 1
        return node_a, node_b

    @staticmethod
    def _auto_name(point):
        return f'节点({point[0]:.5f},{point[1]:.5f})'


def import_geojson(payload, *, replace=False):
    """导入 QGIS GeoJSON，返回导入报告（幂等：同名/同坐标节点复用，重复边跳过）。"""
    points, lines, polygons = collect(payload)

    all_points = [p for p in points]
    for start, end, _props, path in lines:
        all_points.extend(path)
    for polygon in polygons:
        for ring in polygon['rings']:
            all_points.extend(ring)
    if not all_points:
        raise GeoJSONError('GeoJSON 中没有可识别的点/线/面要素')

    lons = [p[0] for p in all_points]
    lats = [p[1] for p in all_points]
    bounds = [min(lons), min(lats), max(lons), max(lats)]
    if bounds[0] == bounds[2] and bounds[1] == bounds[3]:
        # 单点地图：给一个很小范围，避免前端除零
        bounds = [bounds[0] - 0.001, bounds[1] - 0.001, bounds[0] + 0.001, bounds[1] + 0.001]

    from apps.common.context import get_competition_alias

    with transaction.atomic(using=(get_competition_alias() or 'default')):
        if replace:
            MapEdge.objects.all().delete()
            MapNode.objects.all().delete()

        importer = _Importer()

        for lon, lat, props in points:
            importer.node_at(
                lon, lat,
                name=_prop(props, _NAME_KEYS, ''),
                node_type=_prop(props, _NODE_TYPE_KEYS, ''),
                region=_prop(props, _REGION_KEYS, ''),
            )
            region = str(_prop(props, _REGION_KEYS, '') or '').strip()
            if region:
                importer.explicit_regions.add(region)

        for start, end, props, path in lines:
            importer.edge(start, end, props, path)

        # 面 → 区域：给面内且未显式指定区域的节点归区
        for index, polygon in enumerate(polygons):
            name = (polygon.get('name') or '').strip() or f'区域{index + 1}'
            polygon['name'] = name
            importer.report['regions'] += 1
            for node in MapNode.objects.filter(region=''):
                if any(point_in_ring(float(node.x), float(node.y), ring)
                       for ring in polygon['rings']):
                    node.region = name
                    node.save(update_fields=['region', 'updated_at'])

        settings = MapSettings.load()
        settings.mode = MapSettings.MODE_GEO
        settings.bounds = bounds
        settings.regions = polygons
        settings.source = 'geojson'
        settings.imported_at = timezone.now()
        settings.save()

        # 线要素同样要平面化：端点吸附 + T 型接头 + 交点打断，导航才有真正的路网
        from .map_rebuild import rebuild_topology
        topology = rebuild_topology(apply=True)
        # 矿点按最近城市归入原料（产地 + 空价），价格后续人工填
        from .map_materials import sync_mine_materials
        materials = sync_mine_materials(apply=True)
        # 城市节点归区：把节点 region 文本对到 Region 实体（缺的自动建、名称归一）
        from apps.competition.regions import nodes as region_nodes
        try:
            regions_sync = region_nodes.assign_nodes_to_regions()
        except Exception as exc:  # noqa: BLE001 —— 归区失败不影响导入结果
            regions_sync = {'error': f'{type(exc).__name__}: {exc}'}
        # 其他节点归城市：车站/机场/码头按命名规律，矿点等按就近城市兜底
        from apps.competition.regions import city_nodes
        try:
            cities_sync = city_nodes.assign_nodes_to_cities()
        except Exception as exc:  # noqa: BLE001 —— 归城市失败不影响导入结果
            cities_sync = {'error': f'{type(exc).__name__}: {exc}'}

    importer.report['bounds'] = bounds
    importer.report['topology'] = topology
    importer.report['materials'] = materials
    importer.report['regionsSync'] = regions_sync
    importer.report['citiesSync'] = cities_sync
    return importer.report
