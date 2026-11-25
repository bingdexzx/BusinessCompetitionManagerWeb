#!/usr/bin/env python3
"""把运行时的插件 API 同步进 SDK（保证 IDE 提示与真实签名一致）。

运行时改动 ``BusinessCompetitionManagerWeb/plugins_runtime/api.py`` 或 ``ops.py`` 后，
在仓库根目录执行：

    python tools/plugin-sdk/sync_runtime.py
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'BusinessCompetitionManagerWeb' / 'plugins_runtime'
TARGET = Path(__file__).resolve().parent / 'bcm_plugin_sdk' / '_runtime'

FILES = {
    'api.py': 'api.py',
    'ops.py': 'ops.py',
}


def sync() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in FILES.items():
        text = (RUNTIME / source_name).read_text(encoding='utf-8')
        # 运行时是独立包 plugins_runtime，SDK 里变成子包相对导入
        text = text.replace('from plugins_runtime import ops', 'from . import ops')
        (TARGET / target_name).write_text(text, encoding='utf-8')
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]
        print(f'同步 {source_name} → bcm_plugin_sdk/_runtime/{target_name}  sha={digest}')
    print('完成。SDK 与运行时一致。')


if __name__ == '__main__':
    sync()
