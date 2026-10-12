"""基础数据域服务：区域总览兼容实现（旧系统 apps.regions.views._get_map_overview）。

旧结构 MapRegion → 新结构 MapNode/MapEdge 口径：按地图节点所属区域（MapNode.region）
聚合，返回与旧调用方兼容的形状 ``[{region, cards: [...]}]``。旧「区域总览卡片」概念
在新结构中不存在（cards 恒为空，调用方按「区域服务不可用」分支回落静态值，语义一致）。

被 apps.competition.stock.engine._load_map_overview 以可插拔入口调用：
``apps.competition.basedata.services.get_map_overview``。
"""

from apps.common.context import get_competition_id


def get_map_overview(competition_id=None) -> list:
    """按 MapNode/MapEdge 聚合区域总览；不在对应比赛上下文时返回 []（回退空）。

    返回：[{region, nodeCount, edgeCount, cards: []}]，按 region 升序。
    """
    from .models import MapEdge, MapNode

    if competition_id and get_competition_id() != competition_id:
        # 比赛上下文与请求的比赛不一致：不跨库读取，按数据源不可用回退空
        return []
    if get_competition_id() is None:
        return []

    node_counts = {}
    for region in MapNode.objects.values_list('region', flat=True):
        key = region or ''
        node_counts[key] = node_counts.get(key, 0) + 1

    # 边数按起终点节点的区域聚合（一条边两端同区只计一次）
    edge_counts = {}
    edges = MapEdge.objects.values_list('from_node__region', 'to_node__region')
    for from_region, to_region in edges:
        for key in {from_region or '', to_region or ''}:
            edge_counts[key] = edge_counts.get(key, 0) + 1

    regions = set(node_counts) | set(edge_counts)
    return [
        {
            'region': region,
            'nodeCount': node_counts.get(region, 0),
            'edgeCount': edge_counts.get(region, 0),
            'cards': [],
        }
        for region in sorted(regions)
    ]
