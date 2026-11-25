"""地图几何工具（纯函数，不依赖 Django/ORM）。

从 ``map_import`` 抽出，供导入、拓扑重建、单元测试共用：
- 距离：经纬度走球面（haversine），非经纬度的平面地图坐标按欧氏（1 单位≈1km）；
- 点在环内（面图层归区）；
- 线段投影 / 相交（路网平面化用）。
"""
from __future__ import annotations

import math

Point = tuple[float, float]
POINT_EPS = 1e-9

EARTH_RADIUS_KM = 6371.0088


def _looks_like_lonlat(point) -> bool:
    return -180 <= point[0] <= 180 and -90 <= point[1] <= 90


def haversine_km(a, b) -> float:
    """两点经纬度球面距离（km）。"""
    lon1, lat1 = a[0], a[1]
    lon2, lat2 = b[0], b[1]
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, h)))


def is_lonlat(a, b) -> bool:
    """两端点都在经纬度范围内时视为地理坐标。"""
    return _looks_like_lonlat(a) and _looks_like_lonlat(b)


def distance_between(a, b) -> float:
    """地理坐标用球面距离；非经纬度的平面地图坐标用欧氏距离（1 单位≈1km）。"""
    if is_lonlat(a, b):
        return haversine_km(a, b)
    return math.hypot(b[0] - a[0], b[1] - a[1])


def path_length(points) -> float:
    """折线长度（按坐标类型自动选球面/欧氏）。"""
    return sum(distance_between(points[i], points[i + 1]) for i in range(len(points) - 1))


def drop_repeated_points(points, eps: float = 1e-12) -> list[Point]:
    """去掉连续重复点（导入数据里常见 0 长度分段，会让拓扑计算出错）。"""
    clean: list[Point] = []
    for point in points:
        x, y = float(point[0]), float(point[1])
        if clean and abs(clean[-1][0] - x) <= eps and abs(clean[-1][1] - y) <= eps:
            continue
        clean.append((x, y))
    return clean


def point_in_ring(lon, lat, ring) -> bool:
    """射线法判断点是否在多边形环内（环为 [lon, lat] 列表，不要求闭合）。"""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < cross:
                inside = not inside
        j = i
    return inside


def lerp(a, b, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def segment_projection(point, a, b) -> tuple[float, float]:
    """点到线段的投影：返回 (t, 距离)，t 已夹到 [0, 1]。"""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= POINT_EPS:
        return 0.0, math.hypot(point[0] - a[0], point[1] - a[1])
    t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_squared
    t = max(0.0, min(1.0, t))
    px = a[0] + dx * t
    py = a[1] + dy * t
    return t, math.hypot(point[0] - px, point[1] - py)


def segment_intersection(a1, b1, a2, b2, eps: float = 1e-12):
    """两条线段的参数交点 (t, u)；平行/共线返回 None。

    t/u 是各自线段上的比例位置，(t,u) 都在 (0,1) 内才是真正的「中间相交」。
    """
    rx = b1[0] - a1[0]
    ry = b1[1] - a1[1]
    sx = b2[0] - a2[0]
    sy = b2[1] - a2[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) <= eps:
        return None
    qpx = a2[0] - a1[0]
    qpy = a2[1] - a1[1]
    t = (qpx * sy - qpy * sx) / denominator
    u = (qpx * ry - qpy * rx) / denominator
    return t, u
