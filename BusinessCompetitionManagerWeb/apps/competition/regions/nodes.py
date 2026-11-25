"""地图节点 → 区域：把节点的「所属区域」文本对到 Region 记录上（2026-11）。

背景：`MapNode.region` 只是文本，`Region` 是独立实体（区域字段、消费者需求、总览卡片都挂在它上面）。
导入地图后如果文本写法有空格/全角差异，或节点还没填区域，就会出现「区域总览里没有这个区域」。
本函数负责：文本归一 → 建缺失的 Region → 把节点指到规范名称；也支持显式映射一次性归属。
"""

from __future__ import annotations

import re

_SPACE_RE = re.compile(r'\s+')


def normalize_region_name(name) -> str:
    """区域名归一：去首尾空白、压缩连续空白、全角空格转半角。"""
    if name is None:
        return ''
    text = str(name).replace('\u3000', ' ')
    return _SPACE_RE.sub(' ', text).strip()


def assign_nodes_to_regions(*, mapping: dict | None = None,
                            create_missing: bool = True,
                            only_empty: bool = False) -> dict:
    """把地图节点归属到对应区域。

    - 默认按节点自带的 ``region`` 文本归属；``mapping`` 可显式指定
      ``{节点名或节点 ID: 区域名}``，优先级高于文本；
    - ``create_missing=True``：文本对应的 Region 不存在时自动创建；
    - ``only_empty=True``：只处理还没填区域的节点，不覆盖已有归属。

    返回摘要：``created``（新建区域）、``matched``（命中已有区域）、
    ``updated``（节点被改写的条数）、``unassigned``（仍无区域的节点名）、
    ``unknown``（mapping 里找不到的节点）。
    """
    from apps.competition.basedata.models import MapNode
    from apps.competition.regions.models import Region

    mapping = mapping or {}
    by_name = {}
    by_id = {}
    for key, value in mapping.items():
        name = normalize_region_name(value)
        if not name:
            continue
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            by_id[int(key)] = name
        else:
            by_name[normalize_region_name(key)] = name

    regions = {region.name: region for region in Region.objects.all()}
    created, matched = [], []
    updated = 0
    unknown = []
    unassigned = []

    nodes = list(MapNode.objects.all().order_by('id'))
    hit_keys = set()
    for node in nodes:
        target = ''
        if node.id in by_id:
            target = by_id[node.id]
            hit_keys.add(node.id)
        elif normalize_region_name(node.name) in by_name:
            target = by_name[normalize_region_name(node.name)]
            hit_keys.add(normalize_region_name(node.name))
        else:
            target = normalize_region_name(node.region)

        if not target:
            if not only_empty:
                unassigned.append(node.name)
            else:
                unassigned.append(node.name)
            continue
        if only_empty and normalize_region_name(node.region):
            continue

        if target not in regions:
            if not create_missing:
                unassigned.append(node.name)
                continue
            region = Region.objects.create(name=target)
            regions[target] = region
            created.append(target)
        else:
            if target not in matched:
                matched.append(target)

        if node.region != target:
            node.region = target
            node.save(update_fields=['region', 'updated_at'])
            updated += 1

    for key in list(by_id) + [k for k in by_name]:
        if key not in hit_keys:
            unknown.append(key)

    return {
        'created': created,
        'matched': matched,
        'updated': updated,
        'unassigned': unassigned,
        'unknown': unknown,
        'regionCount': len(regions),
    }
