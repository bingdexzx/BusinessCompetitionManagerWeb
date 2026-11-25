"""去掉 map_edges 的「起终点唯一」约束。

路网打断后，同一对节点之间可能有多段路（并行路段），回环也可能回到同一个节点；
旧约束逼着后端二选一：要么删掉一段路（地图缺线），要么在中点补假节点（每次重建
都长出新节点、反复抖动）。放开约束后每条弧段都原样入库，几何一段不丢。
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('basedata', '0005_remove_mapnode_uniq_map_nodes_name'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='mapedge',
            name='uniq_map_edges_from_to',
        ),
    ]
