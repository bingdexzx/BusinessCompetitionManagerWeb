#!/usr/bin/env python3
"""校验 SDK 里内置的运行时副本是否与 plugins_runtime 同步（CI/提交前用）。

退出码：0 = 一致；1 = 有差异（需要执行 sync_runtime.py）。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'BusinessCompetitionManagerWeb' / 'plugins_runtime'
SDK = Path(__file__).resolve().parent / 'bcm_plugin_sdk' / '_runtime'


def normalized(path: Path) -> str:
    text = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    return text.replace('from plugins_runtime import ops', 'from . import ops')


def main() -> int:
    drift = []
    for name in ('api.py', 'ops.py'):
        source = RUNTIME / name
        target = SDK / name
        if not target.exists():
            drift.append(f'{name}: SDK 里缺失')
            continue
        if hashlib.sha256(normalized(source).encode()).digest() != \
                hashlib.sha256(normalized(target).encode()).digest():
            drift.append(f'{name}: 与运行时不一致')
    if drift:
        print('SDK 与运行时不同步：')
        for item in drift:
            print(' -', item)
        print('请执行：python tools/plugin-sdk/sync_runtime.py')
        return 1
    print('SDK 与运行时一致')
    return 0


if __name__ == '__main__':
    sys.exit(main())
