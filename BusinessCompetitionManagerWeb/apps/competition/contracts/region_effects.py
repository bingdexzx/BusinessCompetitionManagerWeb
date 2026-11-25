"""区域字段落账（从 contracts.engine 抽出，降低引擎体积与耦合）。

落账顺序：校验公司所属区域 → 字段附加条件 → 读写区域值 → 不可变审计 + 字段日志。
"""

from apps.competition.contracts.audit import write_field_log
from apps.competition.contracts.errors import ContractError
from apps.competition.contracts.models import Contract, ContractFieldEffect
from apps.competition.contracts.values import effect_after, resolve_effect_company
from apps.competition.regions.models import Region, RegionField
from apps.competition.regions.services import (
    company_belongs_to_region, evaluate_condition,
    read_region_value, write_region_value,
)


def resolve_region(name_or_id):
    """效果里的 ``region`` 可以是区域 ID 或区域名。"""
    raw = str(name_or_id or '').strip()
    if not raw:
        raise ContractError('区域字段效果缺少区域')
    region = Region.objects.filter(pk=int(raw)).first() if raw.isdigit() else None
    if region is None:
        region = Region.objects.filter(name=raw).first()
    if region is None:
        raise ContractError(f'效果指向未知区域：{name_or_id}')
    return region


def apply_region_effect(contract: Contract, effect, companies, *, source, operator):
    """区域字段落账：校验修改条件 → 读写区域值 → 审计 + 字段日志。"""
    acting_company = resolve_effect_company(effect, companies)
    region = resolve_region(effect.region)
    field = RegionField.objects.filter(field_key=effect.field).first()
    if field is None:
        raise ContractError(f'区域字段 {effect.field} 未定义（应由比赛包提供）')

    # 2026-11 口径：公司「所在区域」包含该区域名时，才允许通过合同修改该区域字段
    if not company_belongs_to_region(acting_company, region):
        raise ContractError(
            f'公司「{acting_company.name}」的所在区域不是「{region.name}」，不能修改该区域字段')

    ok, reason = evaluate_condition(acting_company, region, field.condition)
    if not ok:
        raise ContractError(
            f'公司「{acting_company.name}」不满足区域字段「{field.name}」的修改条件：{reason}')

    before = read_region_value(region.id, field.field_key, field.default_value)
    after = effect_after(before, effect.op, effect.value)
    write_region_value(region.id, field.field_key, after)
    ContractFieldEffect.objects.create(
        contract=contract, company=acting_company, region=region,
        field_key=field.field_key, op=effect.op, value_raw=effect.value,
        before_raw=before, after_raw=after, round_no=contract.round_no,
    )
    write_field_log(
        company=acting_company, region=region, field_key=field.field_key,
        op=effect.op, before=before, after=after, source=source, contract=contract,
        round_no=contract.round_no, operator=operator,
    )
