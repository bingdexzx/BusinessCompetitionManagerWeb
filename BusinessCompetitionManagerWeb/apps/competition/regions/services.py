"""区域域服务：消费者需求变更后的联动重算。"""

from __future__ import annotations

import json
import re

# 公司「所在区域」字段键（地图节点区域、区域总览都按它匹配）
LOCATION_FIELD_KEY = 'location'


def recompute_region_demands(region_id: int | None) -> int:
    """消费者需求变更后重算该区域公司的公式字段（旧 `_recompute_dependent_fields` 语义）。

    公式可引用 `consumerDemand` 特殊键（该区域需求总量，见 industries.services）。
    返回受影响公司数。区域不存在/无公司时返回 0。

    回归约定（Decision 4.3）：`consumerDemand` 取值为该区域全部 ConsumerDemand
    的 `quantity` 求和（industries.services._consumer_demand_total，缺省 0），
    而非需求条数；变更任一需求后都按区域触发一次公司公式重算。
    """
    if not region_id:
        return 0
    from apps.competition.companies.models import Company
    from apps.competition.industries.services import recompute_company_fields

    count = 0
    for company in Company.objects.filter(region_id=region_id):
        recompute_company_fields(company)
        count += 1
    return count


# ---------------------------------------------------------------- 区域字段

CONDITION_OPS = ('eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in')
CONDITION_SOURCES = ('COMPANY', 'REGION')


def validate_condition(condition) -> tuple[dict, str]:
    """校验并归一区域字段的修改条件；返回 ``(condition, error)``，空条件表示不限制。

    条件来源 ``source``：``COMPANY``（公司实体字段，默认）/ ``REGION``（目标区域的其他区域字段）。
    """
    if not condition:
        return {}, ''
    if not isinstance(condition, dict):
        return {}, '条件必须是 JSON 对象'
    source = str(condition.get('source') or 'COMPANY').upper()
    if source not in CONDITION_SOURCES:
        return {}, f'条件来源不支持：{source}'
    field_key = str(condition.get('fieldKey') or condition.get('field') or '').strip()
    if not field_key:
        return {}, '条件字段必填'
    op = str(condition.get('op') or 'eq').strip()
    if op not in CONDITION_OPS:
        return {}, f'条件运算符不支持：{op}'
    if 'value' not in condition:
        return {}, '条件值必填'
    return {'source': source, 'fieldKey': field_key, 'op': op, 'value': condition.get('value')}, ''


def _company_field_value(company_id: int, field_key: str):
    from apps.competition.industries.models import CompanyFieldValue

    row = CompanyFieldValue.objects.filter(
        company_id=company_id, field_key=field_key, fiscal_year__isnull=True,
    ).first()
    return row.value if row is not None else None


_LOCATION_SEP = re.compile(r'[,，、;；/|]+')


def _location_tokens(raw) -> set[str]:
    """公司「所在区域」值 → 区域名集合：支持单个名称、逗号/顿号分隔、JSON 数组。"""
    if raw is None:
        return set()
    value = raw
    if isinstance(value, str):
        text = value.strip()
        if text.startswith('[') or text.startswith('"'):
            try:
                value = json.loads(text)
            except (ValueError, TypeError):
                value = text
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    parts = _LOCATION_SEP.split(str(value))
    return {part.strip() for part in parts if part.strip()}


def company_belongs_to_region(company, region) -> bool:
    """公司是否属于该区域：``Company.region`` 指向它，或「所在区域」包含该区域名。

    所在区域支持多值：``"华东,华南"``、``"华东、华南"``、``["华东","华南"]`` 均可。
    """
    if company.region_id and company.region_id == region.id:
        return True
    location = _company_field_value(company.id, LOCATION_FIELD_KEY)
    return (region.name or '').strip() in _location_tokens(location)


def _region_field_value(region_id: int, field_key: str):
    from apps.competition.regions.models import RegionField, RegionFieldValue

    row = RegionFieldValue.objects.filter(
        region_id=region_id, field_key=field_key).first()
    if row is not None:
        return row.value
    definition = RegionField.objects.filter(field_key=field_key).first()
    return definition.default_value if definition is not None else None


def _compare(actual, op: str, expected) -> bool:
    if op == 'in':
        candidates = expected if isinstance(expected, (list, tuple)) else [expected]
        return actual in candidates
    if op in ('gt', 'gte', 'lt', 'lte'):
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return {
            'gt': left > right,
            'gte': left >= right,
            'lt': left < right,
            'lte': left <= right,
        }[op]
    if op == 'ne':
        return actual != expected
    return actual == expected


def evaluate_condition(company, region, condition) -> tuple[bool, str]:
    """判断是否满足区域字段的修改条件；返回 ``(ok, 原因)``。

    ``condition.source`` = REGION 时读目标区域的其他区域字段值，否则读公司实体字段值。
    """
    if not condition:
        return True, ''
    field_key = condition.get('fieldKey') or ''
    if not field_key:
        return True, ''
    source = str(condition.get('source') or 'COMPANY').upper()
    op = condition.get('op') or 'eq'
    expected = condition.get('value')
    if source == 'REGION':
        actual = _region_field_value(region.id, field_key)
        label = f'区域字段 {field_key}'
    else:
        actual = _company_field_value(company.id, field_key)
        label = f'公司字段 {field_key}'

    if _compare(actual, op, expected):
        return True, ''
    return False, f'{label} 当前值 {actual!r} 不满足条件「{op} {expected!r}」'


def read_region_value(region_id: int, field_key: str, default=None):
    from apps.competition.regions.models import RegionFieldValue

    row = RegionFieldValue.objects.filter(
        region_id=region_id, field_key=field_key).first()
    return row.value if row is not None else default


def write_region_value(region_id: int, field_key: str, value):
    """写区域字段值（version+1）；返回 ``RegionFieldValue``。"""
    from apps.competition.regions.models import RegionFieldValue

    row, created = RegionFieldValue.objects.get_or_create(
        region_id=region_id, field_key=field_key,
        defaults={'value': value, 'version': 1},
    )
    if not created:
        row.value = value
        row.version += 1
        row.save(update_fields=['value', 'version', 'updated_at'])
    return row
