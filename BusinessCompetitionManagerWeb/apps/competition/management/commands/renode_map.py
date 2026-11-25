"""重建地图路网拓扑：端点吸附 + T 型接头 + 交点打断。

把「一堆互相压盖、彼此不共享端点的折线」变成真正的节点—弧段图，前端导航就不用再
靠 20×15 网格猜连通了。

用法::

    # 只看报告（默认 dry-run）
    python manage.py renode_map --competition 1

    # 真写库（会先备份 map_nodes / map_edges 到 backup/map_topology/）
    python manage.py renode_map --competition 1 --apply

    # 指定容差（像素地图单位≈km；经纬度地图为度，默认 0.001≈111m）
    python manage.py renode_map --competition comp_51 --apply --tolerance 2
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.common import context as ctx
from apps.competition import provisioning
from apps.competition.basedata import map_rebuild
from apps.competition.basedata.models import MapEdge, MapNode
from apps.global_.competitions.models import Competition


class Command(BaseCommand):
    help = '重建地图拓扑（端点吸附 + T 型接头 + 交点打断）；默认只报告，加 --apply 才写库'

    def add_arguments(self, parser):
        parser.add_argument(
            '--competition', action='append', default=[], metavar='CID_OR_DB',
            help='比赛 id 或比赛库名（可重复）；省略则处理全部比赛',
        )
        parser.add_argument('--tolerance', type=float, help='吸附容差（像素单位≈km / 经纬度为度）')
        parser.add_argument('--apply', action='store_true', help='真正写库（默认只输出报告）')
        parser.add_argument('--skip-backup', action='store_true', help='写库前不备份')
        parser.add_argument('--restore', metavar='BACKUP_JSON',
                            help='用 --apply 生成的备份回滚地图（节点/边），不做重建')
        parser.add_argument('--backup-dir', help='备份目录（默认 backup/map_topology）')

    # ------------------------------------------------------------------ 目标
    def _targets(self, wanted: list[str]) -> list[Competition]:
        competitions = list(Competition.objects.using('default').all().order_by('id'))
        if not wanted:
            return competitions
        picked = []
        for item in wanted:
            token = str(item).strip()
            match = next(
                (c for c in competitions
                 if str(c.id) == token or c.db_name == token),
                None,
            )
            if match is None:
                raise CommandError(f'找不到比赛：{token}')
            if match not in picked:
                picked.append(match)
        return picked

    # ------------------------------------------------------------------ 备份
    def _backup(self, competition: Competition, backup_dir: str | None) -> Path:
        root = Path(backup_dir) if backup_dir else (Path(settings.REPO_ROOT) / 'backup' / 'map_topology')
        root.mkdir(parents=True, exist_ok=True)
        stamp = timezone.now().strftime('%Y%m%d-%H%M%S')
        path = root / f'{competition.db_name}-{stamp}.json'
        payload = {
            'competitionId': competition.id,
            'dbName': competition.db_name,
            'createdAt': timezone.now().isoformat(),
            'nodes': [
                {'id': n.id, 'name': n.name, 'x': n.x, 'y': n.y,
                 'nodeTypeId': n.node_type_id, 'region': n.region}
                for n in MapNode.objects.select_related('node_type').all()
            ],
            'edges': [
                {'id': e.id, 'fromNodeId': e.from_node_id, 'toNodeId': e.to_node_id,
                 'pathTypeId': e.path_type_id, 'distance': e.distance, 'path': e.path}
                for e in MapEdge.objects.all()
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return path

    # ------------------------------------------------------------------ 回滚
    def _restore(self, competition: Competition, backup_path: str) -> tuple[int, int]:
        """整表回滚到备份（节点/边按原 id 重建，并校正自增序列）。"""
        payload = json.loads(Path(backup_path).read_text(encoding='utf-8'))
        node_rows = payload.get('nodes') or []
        edge_rows = payload.get('edges') or []
        with transaction.atomic(using=ctx.get_competition_alias() or 'default'):
            MapEdge.objects.all().delete()
            MapNode.objects.all().delete()
            MapNode.objects.bulk_create([
                MapNode(
                    id=int(node['id']), name=node.get('name') or '',
                    x=float(node.get('x') or 0), y=float(node.get('y') or 0),
                    region=node.get('region') or '',
                    node_type_id=int(node['nodeTypeId']),
                )
                for node in node_rows
            ])
            MapEdge.objects.bulk_create([
                MapEdge(
                    from_node_id=int(edge['fromNodeId']),
                    to_node_id=int(edge['toNodeId']),
                    path_type_id=int(edge['pathTypeId']) if edge.get('pathTypeId') else None,
                    distance=edge.get('distance') or 0,
                    path=edge.get('path') or [],
                )
                for edge in edge_rows
            ])
            self._reset_sequences(ctx.get_competition_alias() or 'default',
                                  ('map_nodes', 'map_edges'))
        return len(edge_rows), len(node_rows)

    @staticmethod
    def _reset_sequences(alias: str, tables) -> None:
        """回填主键后把自增序列拨到 max(id)，避免后续新建撞主键。"""
        from django.db import connections

        for table in tables:
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 0), 1))")

    # ------------------------------------------------------------------ 主流程
    def handle(self, *args, **options):
        competitions = self._targets(options['competition'])
        if not competitions:
            self.stdout.write('没有可处理的比赛')
            return
        failures = 0
        for competition in competitions:
            alias = provisioning.ensure_competition_db(competition.db_name)
            previous = ctx.get_competition_id(), ctx.get_competition_alias()
            ctx.set_competition_context(competition.id, alias)
            try:
                before_nodes = MapNode.objects.count()
                before_edges = MapEdge.objects.count()
                if options.get('restore'):
                    edges, nodes = self._restore(competition, options['restore'])
                    self.stdout.write(self.style.SUCCESS(
                        f'[{competition.db_name}] 已回滚：节点 {nodes}、边 {edges}'))
                    continue
                if not before_edges:
                    self.stdout.write(f'[{competition.db_name}] 没有地图边，跳过')
                    continue
                backup_path = None
                # 先试算：没有变化就别动库、也别生成备份
                report = map_rebuild.rebuild_topology(
                    apply=False, tolerance=options.get('tolerance'))
                if report['changed'] and options['apply']:
                    if not options['skip_backup']:
                        backup_path = self._backup(competition, options.get('backup_dir'))
                    report = map_rebuild.rebuild_topology(
                        apply=True, tolerance=options.get('tolerance'))
                self._print(competition, report, before_nodes, before_edges, backup_path)
            except Exception as exc:  # noqa: BLE001 - 命令要跑完全部比赛
                failures += 1
                self.stderr.write(self.style.ERROR(f'[{competition.db_name}] 失败：{exc}'))
            finally:
                if previous[1]:
                    ctx.set_competition_context(*previous)
                else:
                    ctx.clear_request_context()
        if failures:
            raise CommandError(f'{failures} 个比赛重建失败')

    def _print(self, competition, report, before_nodes, before_edges, backup_path):
        tag = self.style.SUCCESS if report.get('applied') else self.style.WARNING
        passes = report.get('passes') or 1
        head = '已重建' if report.get('applied') else ('无变化' if not report['changed'] else '试算')
        if report.get('applied') and passes > 1:
            head += f'（{passes} 轮逼近）'
        self.stdout.write(tag(f'[{competition.db_name}] {head}'))
        self.stdout.write(
            f'  容差 {report["tolerance"]}　边 {before_edges} → {report["edgesAfter"]}　'
            f'节点 {before_nodes} → {report["nodesAfter"]}'
            f'（新建 {report["nodesCreated"]} / 合并 {report["nodesMerged"]} / 清理 {report.get("nodesRemoved", 0)}）')
        self.stdout.write(
            f'  交点打断 {report["intersections"]}　T 型接头 {report["tJunctions"]}　'
            f'端点吸附 {report["endpointMerges"]}　'
            f'回环 {report["selfLoops"]}　并行路段 {report["parallelArcs"]}')
        if backup_path is not None:
            self.stdout.write(f'  备份：{backup_path}')
        if report['changed'] and not report.get('applied'):
            self.stdout.write('  提示：加 --apply 才会写库')
