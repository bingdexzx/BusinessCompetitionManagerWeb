"""路网平面化（map_topology）单元测试：交点打断 / T 型接头 / 端点吸附 / 幂等。"""

import math
import unittest

from apps.competition.basedata.map_topology import (
    SourceLine, network_of, planarize, planarize_networks,
)


def total_length(result) -> float:
    return sum(arc.length for arc in result.arcs)


def largest_component(result) -> int:
    parent = {}

    def find(item):
        root = item
        while parent.setdefault(root, root) != root:
            root = parent[root]
        while parent[item] != root:
            parent[item], item = root, parent[item]
        return root

    for arc in result.arcs:
        left, right = find(arc.start), find(arc.end)
        if left != right:
            parent[left] = right
    sizes = {}
    for arc in result.arcs:
        root = find(arc.start)
        sizes[root] = sizes.get(root, 0) + 1
    return max(sizes.values()) if sizes else 0


class CrossingTest(unittest.TestCase):
    """十字交叉：两条线在中间相交，必须各自被切开。"""

    def setUp(self):
        self.result = planarize([
            SourceLine(key=1, points=[(0, 0), (10, 0)]),
            SourceLine(key=2, points=[(5, -5), (5, 5)]),
        ], tolerance=0.1)

    def test_one_intersection_node_created(self):
        self.assertEqual(self.result.stats['intersections'], 1)
        # 4 个端点 + 1 个交点
        self.assertEqual(len(self.result.nodes), 5)

    def test_lines_are_split_into_four_arcs(self):
        self.assertEqual(len(self.result.arcs), 4)
        self.assertAlmostEqual(total_length(self.result), 20.0, places=6)

    def test_both_lines_touch_the_intersection_node(self):
        center = [node for node in self.result.nodes.values()
                  if abs(node.x - 5) < 1e-9 and abs(node.y) < 1e-9]
        self.assertEqual(len(center), 1)
        touching = [arc for arc in self.result.arcs if center[0].key in (arc.start, arc.end)]
        self.assertEqual(len(touching), 4)


class EndpointSnapTest(unittest.TestCase):
    """端点吸附：容差内的两个端点并成一个节点。"""

    def test_within_tolerance_merges(self):
        result = planarize([
            SourceLine(key=1, points=[(0, 0), (10, 0)]),
            SourceLine(key=2, points=[(10.4, 0.3), (20, 0)]),
        ], tolerance=1.0)
        self.assertEqual(len(result.arcs), 2)
        self.assertEqual(largest_component(result), 2)
        # 中点处应只有一个节点（两个端点合并）
        shared = [node for node in result.nodes.values()
                  if math.hypot(node.x - 10, node.y) <= 1.0]
        self.assertEqual(len(shared), 1)

    def test_beyond_tolerance_stays_separate(self):
        result = planarize([
            SourceLine(key=1, points=[(0, 0), (10, 0)]),
            SourceLine(key=2, points=[(10.4, 0.3), (20, 0)]),
        ], tolerance=0.1)
        self.assertEqual(len(result.arcs), 2)
        self.assertEqual(largest_component(result), 1)


class TJunctionTest(unittest.TestCase):
    """T 型接头：一条线的端点落在另一条线内部时把后者切开。"""

    def test_endpoint_on_segment_splits_it(self):
        result = planarize([
            SourceLine(key=1, points=[(0, 0), (10, 0)]),
            SourceLine(key=2, points=[(5, 0.4), (5, 8)]),
        ], tolerance=1.0)
        self.assertEqual(result.stats['tJunctions'], 1)
        self.assertEqual(len(result.arcs), 3)
        self.assertEqual(largest_component(result), 3)
        # 端点被焊到对方线的投影点（5, 0.4 → 5, 0），所以竖线剩 8.0km
        self.assertAlmostEqual(total_length(result), 10.0 + 8.0, places=6)


class SharedNodeTest(unittest.TestCase):
    """同一个 MapNode 的端点必须合并，即使几何坐标有偏差。"""

    def test_same_node_id_merges(self):
        result = planarize([
            SourceLine(key=1, points=[(0, 0), (10, 0)], start_node=7, end_node=8),
            SourceLine(key=2, points=[(12, 0.5), (20, 0)], start_node=8, end_node=9),
        ], tolerance=0.01)
        self.assertEqual(len(result.arcs), 2)
        self.assertEqual(largest_component(result), 2)
        merged = [node for node in result.nodes.values() if 8 in node.node_ids]
        self.assertEqual(len(merged), 1)


class IdempotencyTest(unittest.TestCase):
    """已经打断过的图再打断一次不应产生新节点/新弧段。"""

    def test_second_pass_is_stable(self):
        lines = [
            SourceLine(key=1, points=[(0, 0), (10, 0)]),
            SourceLine(key=2, points=[(5, -5), (5, 5)]),
            SourceLine(key=3, points=[(2, 2), (8, 8)]),
        ]
        first = planarize(lines, tolerance=0.2, geo=False)
        again = [
            SourceLine(key=arc.line_key, points=arc.points,
                       start_node=None, end_node=None)
            for arc in first.arcs
        ]
        second = planarize(again, tolerance=0.2, geo=False)
        self.assertEqual(second.stats['intersections'], 0)
        self.assertEqual(len(second.arcs), len(first.arcs))
        self.assertAlmostEqual(total_length(second), total_length(first), places=6)


class ParallelArcTest(unittest.TestCase):
    """两条线连同一对节点：两段路都要留着（落库时在中点补节点切开）。"""

    def test_parallel_arcs_are_both_kept(self):
        result = planarize([
            SourceLine(key=1, points=[(0, 0), (10, 0)]),
            SourceLine(key=2, points=[(0, 0), (4, 3), (10, 0)]),
        ], tolerance=0.1)
        self.assertEqual(len(result.arcs), 2)
        self.assertAlmostEqual(
            total_length(result), 10.0 + 5.0 + math.hypot(6, 3), places=6)


class SelfIntersectionTest(unittest.TestCase):
    """同一条线自交（8 字型）也要打断。"""

    def test_bowtie_splits_at_crossing(self):
        result = planarize([
            SourceLine(key=1, points=[(0, 0), (10, 10), (10, 0), (0, 10)]),
        ], tolerance=0.1)
        self.assertEqual(result.stats['intersections'], 1)
        # 中间的回环保留为「起点=终点」的弧，导航侧会忽略
        self.assertEqual(len(result.arcs), 3)
        self.assertAlmostEqual(total_length(result), 38.284, places=3)


class DegenerateInputTest(unittest.TestCase):
    """退化输入：重复点、单点线、空集合都不应炸。"""

    def test_repeated_points_are_dropped(self):
        result = planarize([
            SourceLine(key=1, points=[(0, 0), (0, 0), (5, 0), (5, 0)]),
        ], tolerance=0.1)
        self.assertEqual(len(result.arcs), 1)

    def test_single_point_line_is_skipped(self):
        result = planarize([SourceLine(key=1, points=[(1, 1)])], tolerance=0.1)
        self.assertEqual(result.arcs, [])
        self.assertEqual(result.stats['arcs'], 0)

    def test_empty_input(self):
        result = planarize([], tolerance=0.1, geo=False)
        self.assertEqual(result.arcs, [])
        self.assertEqual(result.stats['lines'], 0)

    def test_invalid_tolerance(self):
        with self.assertRaises(ValueError):
            planarize([SourceLine(key=1, points=[(0, 0), (1, 0)])], tolerance=0)


class LonLatTest(unittest.TestCase):
    """经纬度地图的弧长要按球面距离（约 111km/度）算。"""

    def test_degree_length_is_metric(self):
        result = planarize([
            SourceLine(key=1, points=[(120.0, 30.0), (120.0, 31.0)]),
        ], tolerance=0.0001, geo=True)
        self.assertEqual(len(result.arcs), 1)
        self.assertAlmostEqual(result.arcs[0].length, 111.19, delta=0.5)


class NetworkClassTest(unittest.TestCase):
    """路径类型要归到正确的网络：公路/铁路才打断，航空/水路整条保留。"""

    def test_network_of(self):
        self.assertEqual(network_of('公路干线'), 'road')
        self.assertEqual(network_of('公路支线'), 'road')
        self.assertEqual(network_of('铁路干线'), 'rail')
        self.assertEqual(network_of('航空线'), 'air')
        self.assertEqual(network_of('水路线'), 'water')
        self.assertEqual(network_of(''), 'road')


class CrossNetworkTest(unittest.TestCase):
    """不同网络互不打断：公路穿过航线，两边都保持整条。"""

    def setUp(self):
        self.groups = {
            'road': [SourceLine(key=1, points=[(0, 0), (10, 0)])],
            'air': [SourceLine(key=2, points=[(5, -5), (5, 5)])],
        }
        self.result = planarize_networks(self.groups, tolerance=0.1)

    def test_no_cross_network_intersection(self):
        self.assertEqual(self.result.stats['intersections'], 0)
        self.assertEqual(len(self.result.arcs), 2)

    def test_same_network_still_splits(self):
        groups = {
            'road': [
                SourceLine(key=1, points=[(0, 0), (10, 0)]),
                SourceLine(key=2, points=[(5, -5), (5, 5)]),
            ],
        }
        result = planarize_networks(groups, tolerance=0.1)
        self.assertEqual(result.stats['intersections'], 1)
        self.assertEqual(len(result.arcs), 4)


class WholeLineTest(unittest.TestCase):
    """航空/水路整条保留，但共用机场/码头节点时要连得上。"""

    def test_air_lines_share_airport_node(self):
        result = planarize_networks({
            'air': [
                SourceLine(key=1, points=[(0, 0), (10, 0)], start_node=1, end_node=2),
                SourceLine(key=2, points=[(10, 0), (20, 5)], start_node=2, end_node=3),
            ],
        }, tolerance=0.1)
        self.assertEqual(len(result.arcs), 2)
        self.assertEqual(largest_component(result), 2)
        airport = [node for node in result.nodes.values() if 2 in node.node_ids]
        self.assertEqual(len(airport), 1)
        self.assertAlmostEqual(total_length(result), math.hypot(10, 0) + math.hypot(10, 5), places=6)

    def test_air_line_kept_whole(self):
        result = planarize_networks({
            'air': [SourceLine(key=1, points=[(0, 0), (5, 5), (10, 0)])],
        }, tolerance=0.1)
        self.assertEqual(len(result.arcs), 1)
        self.assertAlmostEqual(total_length(result), math.hypot(5, 5) * 2, places=6)
