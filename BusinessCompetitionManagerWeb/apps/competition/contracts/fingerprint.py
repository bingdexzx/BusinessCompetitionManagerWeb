"""合同实例导入指纹（幂等去重，2026-10 决策）。

重导入比赛包时用来判断「包里这条合同是否已经导入过」，避免重复建合同。
指纹只由**合同内容**决定：类型 + 名称 + 参与方（角色↔公司）+ 输入项，
因此包内改动了名称/参与方/输入 → 指纹变化 → 视为新合同（旧合同保留）。

本模块**刻意不导入 Django**：迁移里补算历史数据时也要用同一套算法。
"""

import hashlib
import json


def contract_fingerprint(contract_type_key, name, parties, inputs) -> str:
    """返回合同实例指纹（sha256 十六进制，64 字符）。"""
    normalized_parties = sorted(
        [[str(p.get('role') or ''), p.get('companyId')] for p in (parties or [])],
        key=lambda item: (item[0], item[1] or 0),
    )
    payload = {
        'type': str(contract_type_key or ''),
        'name': str(name or ''),
        'parties': normalized_parties,
        'inputs': inputs or {},
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()
