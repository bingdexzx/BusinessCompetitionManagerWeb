"""冻结口径调整（2026-11）：落账不再冻结；仅合同修改期间冻结参与方公司全部资源。

存量数据修正：
1. 旧口径按字段长期冻结的行 → 全部解除（否则手工修改会被历史合同永久挡住）；
2. 当前处于修改流程（MOD_APPLYING / MOD_EDITING）的合同 → 补齐 ``field_key='*'`` 整公司冻结行。

注意：比赛域模型受上下文守卫约束，迁移时需要按当前连接 alias 设置比赛上下文。
"""

from django.db import migrations

UNFROZE_REASON = '冻结口径调整（2026-11）：仅在合同修改期间冻结，历史落账冻结解除'


def apply_new_semantics(apps, schema_editor):
    from django.utils import timezone

    from apps.common import context as ctx

    alias = schema_editor.connection.alias
    Competition = apps.get_model('competitions', 'Competition')
    competition = Competition.objects.using('default').filter(db_name=alias).first()
    if competition is None:
        return  # 非比赛库（default / 测试库以外的未知 alias）：无需数据修正

    ContractFreeze = apps.get_model('ledger', 'ContractFreeze')
    Contract = apps.get_model('contracts', 'Contract')

    ctx.set_competition_context(competition.id, alias)
    try:
        now = timezone.now()
        ContractFreeze.objects.filter(unfrozen_at__isnull=True).update(
            unfrozen_at=now, reason=UNFROZE_REASON,
        )
        for contract in Contract.objects.filter(status__in=['MOD_APPLYING', 'MOD_EDITING']):
            label = contract.unified_number or contract.id
            company_ids = {
                p.get('companyId') for p in (contract.parties or []) if p.get('companyId')
            }
            for company_id in company_ids:
                ContractFreeze.objects.get_or_create(
                    contract=contract, company_id=company_id, field_key='*',
                    defaults={'reason': f'合同 {label} 修改中，资源冻结'},
                )
    finally:
        ctx.clear_request_context()


class Migration(migrations.Migration):

    dependencies = [
        ('ledger', '0001_initial'),
        ('contracts', '0008_contract_import_fingerprint'),
    ]

    operations = [
        migrations.RunPython(apply_new_semantics, migrations.RunPython.noop),
    ]
