"""QGIS 工程（.qgz）多图层导入（纯 Python，无需 QGIS）。

.qgz 本质是 ZIP，里含 .qgs 工程 XML；工程引用同目录/绝对路径的 Shapefile。
读取 .qgs 的图层名与数据源，用 pyshp 读取点/线/面：
- 点 → 地图节点（节点类型 = 图层名）
- 线 → 地图边（路径类型 = 图层名，保留完整折线路径）
- 面 → 区域面 / 装饰图层（MapSettings.layers）
- 省级面图层（名称以“省”结尾）→ 创建 Region 实体并把点归入省份
"""
from __future__ import annotations

import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .map_import import (
    GeoJSONError, _Importer, point_in_ring,
)
from .models import MapEdge, MapNode, MapSettings

POLYGON_COLORS = [
    '#F2A65A', '#7FB3D5', '#82C09A', '#E08B8B', '#B8A1D9',
    '#E6C56B', '#93C6C0', '#D8A7B1', '#A9C47F', '#C9B79C',
]
_NAME_PRIORITY = (
    'city_name', '城市名', '市名', '省份名', '省份', 'name',
    '机场', '火车站', '码头', '高速站口', '高速站', '种类', '水路', '铁路干线', '航空线',
)
_MAX_POLYGON_FEATURES = 4000

# 点图层的省份属性：源文件（Shapefile 的 DBF 字段名常是大写、中文也可能是「省份名/所在省」）
# 各种写法都认一下；读不到就退回到面图层的几何归属。
_PROVINCE_FIELDS = (
    'province', 'prov', 'province_name', 'provincename', 'prov_name', 'city_province',
    'provinceid', 'prov_id', '省份', '省', '省份名', '省名', '所在省', '所在省份',
)


def _norm_key(name) -> str:
    return str(name or '').strip().lower().replace(' ', '').replace('_', '').replace('-', '')


_PROVINCE_KEYS = {_norm_key(item) for item in _PROVINCE_FIELDS}


def _province_of(props: dict) -> str:
    for key, value in (props or {}).items():
        if _norm_key(key) in _PROVINCE_KEYS:
            text = _text(value)
            if text:
                return text
    return ''


def _text(value) -> str:
    return '' if value is None else str(value).strip()


def _find_project_qgs(root: Path) -> Path:
    projects = sorted(root.rglob('*.qgs'))
    if not projects:
        raise GeoJSONError('压缩包/工程中没有 .qgs 文件')
    return projects[0]


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def _read_layers(qgs_path: Path) -> list[dict]:
    try:
        tree = ET.parse(qgs_path)
    except ET.ParseError as exc:
        raise GeoJSONError(f'QGIS 工程 XML 解析失败：{exc}') from exc
    root = tree.getroot()
    visible_by_id: dict[str, bool] = {}
    for node in root.iter():
        if _local(node.tag) != 'layer-tree-layer':
            continue
        layer_id = node.attrib.get('id') or ''
        checked = node.attrib.get('checked')
        visible_by_id[layer_id] = checked not in ('Qt::Unchecked', 'false', '0')

    layers: list[dict] = []
    for node in root.iter():
        if _local(node.tag) != 'maplayer':
            continue
        layer_id = node.attrib.get('id') or ''
        values = {_local(child.tag): child.text or '' for child in list(node)}
        source = (values.get('datasource') or '').strip().strip('"')
        if not source.lower().endswith('.shp'):
            continue
        name = (values.get('layername') or values.get('name')
                or Path(source).stem).strip()
        layers.append({
            'id': layer_id,
            'name': name,
            'source': source,
            'visible': visible_by_id.get(layer_id, True),
        })
    if not layers:
        raise GeoJSONError('工程中未找到 Shapefile 矢量图层（暂不支持 GeoPackage）')
    return layers


def _resolve_source(source: str, project_dir: Path, original_dir: Path | None = None) -> Path:
    raw = source.replace('\\', '/')
    candidate = Path(raw)
    candidates = [candidate] if candidate.is_absolute() else [
        project_dir / raw,
        (original_dir / raw) if original_dir else None,
    ]
    for item in candidates:
        if item is not None and item.exists():
            return item
    # 工程里可能写了原作者的相对路径（如 ../../Documents/xxx.shp）；
    # 优先按文件名在工程目录/上传目录内查找。
    file_name = Path(raw).name
    for base in (project_dir, original_dir):
        if base is None:
            continue
        direct = base / file_name
        if direct.exists():
            return direct
        matches = list(base.rglob(file_name))
        if matches:
            return matches[0]
    raise GeoJSONError(f'找不到图层数据源：{source}')


def _shapefile_features(path: Path):
    try:
        import shapefile
    except ImportError as exc:
        raise GeoJSONError('服务器缺少 pyshp 依赖，无法读取 Shapefile') from exc
    try:
        reader = shapefile.Reader(str(path), encoding='utf-8', encodingErrors='replace')
    except Exception as exc:
        raise GeoJSONError(f'Shapefile 读取失败：{path.name}：{exc}') from exc
    fields = [field[0] for field in reader.fields[1:]]
    try:
        for index, shape in enumerate(reader.shapes()):
            record = reader.record(index)
            props = {}
            for position, field in enumerate(fields):
                try:
                    props[field] = record[position]
                except (IndexError, KeyError):
                    props[field] = None
            yield shape, props
    finally:
        reader.close()


def _shape_kind(shape) -> str:
    shape_type = int(getattr(shape, 'shapeType', 0) or 0)
    if shape_type in (1, 11, 21):
        return 'POINT'
    if shape_type in (8, 18, 28):
        return 'MULTIPOINT'
    if shape_type in (3, 13, 23):
        return 'LINE'
    if shape_type in (5, 15, 25):
        return 'POLYGON'
    return 'UNKNOWN'


def _parts(shape) -> list[list[tuple[float, float]]]:
    points = [(float(x), float(y)) for x, y in (shape.points or [])]
    parts = list(shape.parts or [0])
    if not points:
        return []
    out = []
    for idx, start in enumerate(parts):
        end = parts[idx + 1] if idx + 1 < len(parts) else len(points)
        out.append(points[start:end])
    return out


def _feature_name(props: dict, fields: list[str], layer: str, index: int) -> str:
    for key in _NAME_PRIORITY:
        value = _text((props or {}).get(key))
        if value:
            return value
    for key in fields:
        if key == 'id':
            continue
        value = _text((props or {}).get(key))
        if value:
            return value
    return f'{layer}-{index + 1}'


def _is_province_layer(name: str) -> bool:
    return name.endswith('省')


def _snap_edges_to_points(bounds: list[float]) -> None:
    """把线路端点节点吸附到最近的城市/机场/码头/车站/高速口，连通路网。

    QGIS 线图层的端点与点位图层常有 0.5~3 个地图单位的偏差；不吸附时
    每条线都是独立小组件，导航会显示“无路径”。
    """
    import math

    from .models import MapEdge, MapNode

    min_lon, min_lat, max_lon, max_lat = bounds
    span = max(max_lon - min_lon, max_lat - min_lat)
    if -180 <= min_lon <= 180 and -90 <= min_lat <= 90 and span <= 360:
        tolerance = 0.005  # 经纬度地图约 500m
    else:
        tolerance = max(3.0, span * 0.004)

    point_types = ('城市点位', '机场', '码头', '火车站', '高速口', '行政区域划分')
    point_nodes = list(
        MapNode.objects.filter(node_type__name__in=point_types)
        .select_related('node_type')
    )
    if not point_nodes:
        return

    def nearest_point(x: float, y: float):
        best = None
        best_distance = tolerance
        for point in point_nodes:
            distance = math.hypot(point.x - x, point.y - y)
            if distance <= best_distance:
                best = point
                best_distance = distance
        return best

    touched = set()
    for edge in list(MapEdge.objects.select_related('from_node', 'to_node')):
        from_node = edge.from_node
        to_node = edge.to_node
        new_from = from_node
        new_to = to_node
        if from_node.node_type.name == '默认节点':
            snapped = nearest_point(from_node.x, from_node.y)
            if snapped is not None:
                new_from = snapped
                touched.add(from_node.id)
        if to_node.node_type.name == '默认节点':
            snapped = nearest_point(to_node.x, to_node.y)
            if snapped is not None:
                new_to = snapped
                touched.add(to_node.id)
        if new_from.id == new_to.id:
            edge.delete()
            continue
        if new_from.id == from_node.id and new_to.id == to_node.id:
            continue
        duplicate = (
            MapEdge.objects
            .filter(from_node=new_from, to_node=new_to)
            .exclude(pk=edge.pk)
            .exists()
            or MapEdge.objects
            .filter(from_node=new_to, to_node=new_from)
            .exclude(pk=edge.pk)
            .exists()
        )
        if duplicate:
            edge.delete()
            continue
        path = edge.path or []
        if path and new_from.id != from_node.id:
            path[0] = [new_from.x, new_from.y]
        if path and new_to.id != to_node.id:
            path[-1] = [new_to.x, new_to.y]
        edge.from_node = new_from
        edge.to_node = new_to
        edge.path = path
        edge.save(update_fields=['from_node', 'to_node', 'path', 'updated_at'])

    # 吸附后端点节点可能已没有边，清理掉，避免左/图例出现孤立点
    for node_id in touched:
        node = MapNode.objects.filter(pk=node_id).first()
        if node is not None and not MapEdge.objects.filter(
            from_node=node
        ).exists() and not MapEdge.objects.filter(to_node=node).exists():
            node.delete()


def import_qgis_project(project_path: Path, *, replace: bool = False) -> dict:
    project_path = Path(project_path)
    temp_dir = Path(tempfile.mkdtemp(prefix='qgis_import_'))
    try:
        if project_path.suffix.lower() == '.qgz':
            try:
                with zipfile.ZipFile(project_path) as archive:
                    archive.extractall(temp_dir)
            except zipfile.BadZipFile as exc:
                raise GeoJSONError('不是有效的 .qgz 工程文件') from exc
            qgs_path = _find_project_qgs(temp_dir)
        elif project_path.suffix.lower() == '.qgs':
            qgs_path = project_path
        else:
            raise GeoJSONError('只支持 .qgz / .qgs 工程')
        layers = _read_layers(qgs_path)
        resolved = []
        missing = []
        for layer in layers:
            try:
                layer['path'] = _resolve_source(
                    layer['source'], qgs_path.parent, project_path.parent)
                resolved.append(layer)
            except GeoJSONError:
                missing.append(layer['name'])
        if not resolved:
            raise GeoJSONError(
                '找不到图层数据源。请把 .qgz 和同目录的 .shp/.dbf/.shx/.prj 一起打成 ZIP 上传')
        report = _import_layers(resolved, replace=replace)
        if missing:
            report['missingLayers'] = missing
        return report
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _import_layers(layers: list[dict], *, replace: bool) -> dict:
    if replace:
        MapEdge.objects.all().delete()
        MapNode.objects.all().delete()

    importer = _Importer()
    layer_meta: list[dict] = []
    region_polygons: list[dict] = []
    region_layers: set[str] = set()
    all_points: list[tuple[float, float]] = []
    feature_layers: list[dict] = []

    # 先读取每个 Shapefile 的要素，按几何类型分类
    for item in layers:
        path = item['path']
        features = list(_shapefile_features(path))
        if not features:
            continue
        kind = _shape_kind(features[0][0])
        if not features:
            continue
        fields = list(features[0][1].keys())
        feature_layers.append({**item, 'features': features, 'kind': kind, 'fields': fields})

    # 1) 面图层：省级图层建区域，其余作为面图层（可开关）
    for order, item in enumerate(feature_layers):
        if item['kind'] != 'POLYGON':
            continue
        is_province = _is_province_layer(item['name'])
        province_color = POLYGON_COLORS[order % len(POLYGON_COLORS)]
        features_out = []
        for index, (shape, props) in enumerate(item['features']):
            name = _feature_name(props, item['fields'], item['name'], index)
            for rings in _parts(shape):
                if len(rings) < 3:
                    continue
                all_points.extend(rings)
                region = item['name'] if is_province else ''
                feature = {
                    'name': '' if is_province else name,
                    'region': region,
                    'rings': [[[lon, lat] for lon, lat in rings]],
                    'color': province_color,
                }
                features_out.append(feature)
                if is_province:
                    region_polygons.append({'name': item['name'], 'rings': rings})
            if len(features_out) >= _MAX_POLYGON_FEATURES:
                break
        if is_province:
            region_layers.add(item['name'])
            layer_meta.append({
                'name': item['name'], 'kind': 'POLYGON', 'role': 'REGION',
                'color': province_color, 'visible': True, 'features': features_out,
            })
        else:
            layer_meta.append({
                'name': item['name'], 'kind': 'POLYGON',
                'role': 'DECORATION',
                'color': POLYGON_COLORS[order % len(POLYGON_COLORS)],
                'visible': False,
                'features': features_out,
            })

    # 2) 点/线
    for order, item in enumerate(feature_layers):
        if item['kind'] not in ('POINT', 'MULTIPOINT', 'LINE'):
            continue
        if item['kind'] in ('POINT', 'MULTIPOINT'):
            for index, (shape, props) in enumerate(item['features']):
                name = _feature_name(props, item['fields'], item['name'], index)
                region = _province_of(props)
                for part in _parts(shape):
                    for lon, lat in part:
                        all_points.append((lon, lat))
                        importer.node_at(
                            lon, lat, name=name, node_type=item['name'], region=region,
                            unique_name=False, reuse_coord=False)
            node_type = importer.node_type(item['name'])
            layer_meta.append({
                'name': item['name'], 'kind': 'POINT', 'role': 'NODE',
                'color': node_type.color or '', 'visible': bool(item.get('visible', True)),
                'nodeTypeId': node_type.id, 'features': [],
            })
        else:
            for index, (shape, props) in enumerate(item['features']):
                for path in _parts(shape):
                    if len(path) < 2:
                        continue
                    all_points.extend(path)
                    importer.edge(path[0], path[-1], {**props, 'pathType': item['name']}, path)
            path_type = importer.path_type(item['name'])
            layer_meta.append({
                'name': item['name'], 'kind': 'LINE', 'role': 'EDGE',
                'color': path_type.color or '', 'visible': bool(item.get('visible', True)),
                'pathTypeId': path_type.id, 'features': [],
            })

    # 3) 省份 Region + 点归属
    if region_layers:
        from apps.competition.regions.models import Region
        for name in sorted(region_layers):
            Region.objects.get_or_create(name=name)
        for node in MapNode.objects.filter(region=''):
            for polygon in region_polygons:
                if point_in_ring(node.x, node.y, polygon['rings']):
                    node.region = polygon['name']
                    node.save(update_fields=['region', 'updated_at'])
                    break

    if not all_points:
        raise GeoJSONError('工程图层中没有可识别的坐标')
    lons = [p[0] for p in all_points]
    lats = [p[1] for p in all_points]
    bounds = [min(lons), min(lats), max(lons), max(lats)]
    _snap_edges_to_points(bounds)

    settings = MapSettings.load()
    settings.mode = MapSettings.MODE_GEO
    settings.bounds = bounds
    settings.regions = region_polygons
    settings.layers = layer_meta
    settings.source = 'qgz'
    from django.utils import timezone
    settings.imported_at = timezone.now()
    settings.save()

    # 线图层只是「互相压盖的折线」：端点相碰不共享节点、交叉处也没打断。
    # 统一做一次拓扑重建（端点吸附 + T 型接头 + 交点打断），导航才有真正的路网可用。
    from .map_rebuild import rebuild_topology
    topology = rebuild_topology(apply=True)
    # 矿点按最近城市归入原料（产地 + 空价），价格后续人工填
    from .map_materials import sync_mine_materials
    materials = sync_mine_materials(apply=True)

    importer.report['bounds'] = bounds
    importer.report['layers'] = len(layer_meta)
    importer.report['regionPolygons'] = len(region_polygons)
    importer.report['regions'] = len(region_layers)
    importer.report['topology'] = topology
    importer.report['materials'] = materials
    return importer.report
