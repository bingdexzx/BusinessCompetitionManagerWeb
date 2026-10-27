"""Channel Layer 自检：验证跨进程消息总线（PostgreSQL）可用。

用法：``.venv\\Scripts\\python.exe scripts\\smoke_channel_layer.py``
（需能连到 .env 配置的 PostgreSQL；会在全局库建 2 张 gipfel_channel_* 表）

验证内容：
1. group_add / group_send / receive 组内投递（含往返延迟）；
2. send / receive 点对点投递；
3. 跨进程投递：另起一个子进程 group_send，本进程 receive 能收到（多核部署的关键）。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND = os.path.join(REPO, 'BusinessCompetitionManagerWeb')
sys.path.insert(0, BACKEND)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')

import django  # noqa: E402

django.setup()

from channels.layers import get_channel_layer  # noqa: E402


async def _roundtrip() -> None:
    layer = get_channel_layer()
    print(f'channel layer: {type(layer).__module__}.{type(layer).__name__}')

    channel = await layer.new_channel()
    await layer.group_add('user_smoke', channel)

    t0 = time.perf_counter()
    await layer.group_send('user_smoke', {'type': 'user.notification', 'payload': {'n': 1}})
    msg = await asyncio.wait_for(layer.receive(channel), timeout=5)
    print(f'[1] group_send → receive: {msg}（{1000 * (time.perf_counter() - t0):.0f}ms）')

    t0 = time.perf_counter()
    await layer.send(channel, {'type': 'user.notification', 'payload': {'n': 2}})
    msg = await asyncio.wait_for(layer.receive(channel), timeout=5)
    print(f'[2] send → receive:       {msg}（{1000 * (time.perf_counter() - t0):.0f}ms）')

    await layer.group_discard('user_smoke', channel)
    await layer.flush()


def _child_sender() -> None:
    """子进程：只负责往组里发一条消息（模拟 HTTP worker 进程）。"""
    import django as _django

    _django.setup()
    layer = get_channel_layer()
    asyncio.run(layer.group_send('user_smoke', {'type': 'user.notification', 'payload': {'from': 'child'}}))


async def _cross_process() -> None:
    import multiprocessing

    layer = get_channel_layer()
    channel = await layer.new_channel()
    await layer.group_add('user_smoke', channel)

    ctx = multiprocessing.get_context('spawn')
    proc = ctx.Process(target=_child_sender)
    t0 = time.perf_counter()
    proc.start()
    msg = await asyncio.wait_for(layer.receive(channel), timeout=15)
    proc.join(timeout=5)
    print(f'[3] 跨进程 group_send → receive: {msg}（{1000 * (time.perf_counter() - t0):.0f}ms）')
    await layer.group_discard('user_smoke', channel)
    await layer.flush()


def main() -> int:
    asyncio.run(_roundtrip())
    asyncio.run(_cross_process())
    print('channel layer 自检通过。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
