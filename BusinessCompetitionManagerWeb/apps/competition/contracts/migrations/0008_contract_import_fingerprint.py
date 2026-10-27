"""合同导入指纹（比赛包重导入去重）+ 历史合同补算。

重导入比赛包时按指纹识别「同一条合同是否已存在」，避免重复建合同。
已有的合同（本改动之前导入的）在这里一次性补算，否则第一次重导入仍会重复。
"""

import hashlib
import json

from django.db import migrations, models


def _fingerprint(contract_type_key, name, parties, inputs) -> str:
    """与 ``apps.competition.contracts.fingerprint.contract_fingerprint`` 同一算法。

    迁移刻意内联实现（不 import 应用代码），保证历史数据补算结果永远确定。
    """
    normalized = sorted(
        [[str(p.get('role') or ''), p.get('companyId')] for p in (parties or [])],
        key=lambda item: (item[0], item[1] or 0),
    )
    payload = {
        'type': str(contract_type_key or ''),
        'name': str(name or ''),
        'parties': normalized,
        'inputs': inputs or {},
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def backfill_fingerprints(apps, schema_editor):
    # 显式 using(alias)：迁移期没有比赛上下文，多库路由器会拒绝为比赛域模型选库
    alias = schema_editor.connection.alias
    manager = apps.get_model('contracts', 'Contract').objects.using(alias)
    batch = []
    rows = manager.all().only(
        'id', 'contract_type_key', 'name', 'parties', 'inputs').iterator()
    for contract in rows:
        contract.import_fingerprint = _fingerprint(
            contract.contract_type_key, contract.name, contract.parties, contract.inputs)
        batch.append(contract)
        if len(batch) >= 500:
            manager.bulk_update(batch, ['import_fingerprint'])
            batch = []
    if batch:
        manager.bulk_update(batch, ['import_fingerprint'])


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0007_contract_deleted_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='contract',
            name='import_fingerprint',
            field=models.CharField(
                blank=True, db_index=True, max_length=64,
                verbose_name='导入指纹（重导入去重）'),
        ),
        migrations.RunPython(backfill_fingerprints, migrations.RunPython.noop),
    ]
