"""合同引擎（§3 合同状态机、§7 落账设计、§14.2 字段日志）。

主链（§3.3）：create(DRAFT) → submit(运行 check) → 各方按序 confirm → 编号 → 自动 execute →
再次 check → 落账(POSTED)；修改链 T6→T7→T8→T9/T10（回滚旧落账 + 重检查 + 重执行），驳回回 POSTED。
冻结口径（2026-11 调整）：**仅当公司有合同处于修改流程（申请中/修改中）时，冻结该公司全部资源**，
此时只允许该合同自身的修改流程改字段；修改完成或驳回后自动解冻，平时手工修改不受影响。
补录（决策 D14）：以所补录财年末备份快照为执行基准，落账后非财年定时器字段自动同步（BACKFILL_SYNC）。
执行 = apply 改写 + check + 落账；回滚 = 逆序重放（ADD↔SUB、SET 恢复 beforeRaw，§7.2）。
"""

from django.conf import settings

from django.db import transaction
from django.utils import timezone

import json

from apps.common import context as ctx
from apps.competition.contracts.audit import write_field_log
from apps.competition.contracts.errors import (
    CheckFailedError, ContractError, ContractPermissionError,
)
from apps.competition.contracts.models import (
    Contract, ContractConfirmation, ContractFieldEffect, ContractModRequest, NumberSequence,
)
from apps.competition.contracts.region_effects import apply_region_effect
from apps.competition.contracts.values import effect_after, resolve_effect_company
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.competition.ledger.models import ContractFreeze
from plugins_runtime import ops

__all__ = [
    'CheckFailedError', 'ContractError', 'ContractPermissionError',
    'apply_effects', 'rollback_round',
]


def comp_atomic():
    """比赛库事务（多库架构下事务必须落在比赛库连接上，§5.2）。"""
    return transaction.atomic(using=(ctx.get_competition_alias() or 'default'))


def lock_contract(contract: Contract) -> Contract:
    """取同一张合同的行锁（须在 comp_atomic() 内调用）。

    并发确认 / 重复点提交 / 同时执行时，只有拿到锁的请求能看到并改写最新状态，
    避免「读-判-写」被两个请求同时穿过，造成重复确认或重复落账。
    """
    locked = (type(contract).objects
              .select_for_update()
              .filter(pk=contract.pk, deleted_at__isnull=True)
              .first())
    if locked is None:
        raise ContractError('合同不存在或已删除')
    return locked


def run_locked(contract: Contract, fn):
    """在比赛库事务内锁住合同行后执行 fn(locked)，并把最新状态回写到传入对象。"""
    with comp_atomic():
        locked = lock_contract(contract)
        result = fn(locked)
        contract.refresh_from_db()
        return result


def load_contract_module(contract: Contract):
    """按合同锁定的插件版本加载合同类型插件（§5.4 版本化）。"""
    from apps.competition.contracts.services import contract_module_for
    return contract_module_for(contract.contract_type_key, contract.plugin_version)


def party_company_map(contract: Contract) -> dict:
    """参与方角色 → 公司（一次批量查询，保持 parties 顺序）。"""
    from apps.competition.companies.models import Company

    ids = [p.get('companyId') for p in contract.parties if p.get('companyId')]
    companies = {c.id: c for c in Company.objects.filter(pk__in=ids)} if ids else {}
    out = {}
    for p in contract.parties:
        company = companies.get(p.get('companyId'))
        if company is not None:
            out[p['role']] = company
    return out


def _read_value(company, field_key, fiscal_year):
    """读字段值：精确财年行（财务报表）→ 最新财年行 → 无财年行（实体信息表）。"""
    if fiscal_year is not None:
        row = CompanyFieldValue.objects.filter(
            company=company, field_key=field_key, fiscal_year=fiscal_year).first()
        if row is not None:
            return row.value
    row = (
        CompanyFieldValue.objects
        .filter(company=company, field_key=field_key, fiscal_year__isnull=False)
        .order_by('-fiscal_year__year')
        .first()
    )
    if row is not None:
        return row.value
    row = CompanyFieldValue.objects.filter(
        company=company, field_key=field_key, fiscal_year__isnull=True).first()
    return row.value if row is not None else 0


def _pick_value(rows, fiscal_year):
    """从预取行中按 ``_read_value`` 的优先级取值：精确财年 → 最新财年 → 无财年行 → 0。"""
    if fiscal_year is not None:
        for row in rows:
            if row.fiscal_year_id == fiscal_year.id:
                return row.value
    fiscal_rows = [row for row in rows if row.fiscal_year_id is not None]
    if fiscal_rows:
        return max(fiscal_rows, key=lambda row: row.fiscal_year.year).value
    for row in rows:
        if row.fiscal_year_id is None:
            return row.value
    return 0


def _basis_value(company, field_key, basis):
    """补录合同执行基准（所补录财年末备份快照，§3.4）。"""
    if basis is None:
        return _read_value(company, field_key, None)
    snap = basis.get(company.id) or {}
    return snap.get(field_key, 0)


def node_maps() -> dict:
    """地图节点索引：``{'region': {节点→区域名}, 'city': {节点→城市名}}``。

    一次查询同时给合同插件提供 ctx.region_of / ctx.city_of 的数据源。
    """
    from apps.competition.basedata.models import MapNode

    regions, cities = {}, {}
    for node_id, name, region, city, type_name in MapNode.objects.values_list(
            'id', 'name', 'region', 'city', 'node_type__name'):
        region_name = (region or '').strip()
        city_name = (city or '').strip()
        # 城市点位节点就是城市本体：没有显式 city 时归自己
        if not city_name and type_name == '城市点位' and name:
            city_name = str(name).strip()
        keys = [f'#{node_id}']
        if name:
            keys.append(str(name).strip())
        for key in keys:
            if region_name:
                regions[key] = region_name
            if city_name:
                cities[key] = city_name
    return {'region': regions, 'city': cities}


def node_region_map() -> dict:
    """地图节点 → 区域名（合同插件 ctx.region_of 的数据源）。"""
    return node_maps()['region']


def node_city_map() -> dict:
    """地图节点 → 城市名（合同插件 ctx.city_of 的数据源）。"""
    return node_maps()['city']


def basedata_item_details(table: str) -> dict:
    """基础数据表 → ``{名称: {字段: 值}}``：**该条目的全部字段**（除 id / 创建 / 更新时间）。

    字段名与基础数据模型一致（下划线命名）；``Decimal`` 统一转 float，外键取关联对象名称
    （如地图节点的 ``node_type`` 返回「城市点位」）。另外补上关系型数据，方便插件直接用：

    - ``materials``: 另有 ``origin``（产地名称列表，兼容老数据 JSON 字符串）、
      ``node_prices``（按地点价格 ``{地图节点ID: 价格}``）
    - ``parts``: 另有 ``materials`` 原料配比 ``{原料: 比例}``
    - ``products``: 另有 ``parts`` 零件配比 ``{零件: 比例}``
    - ``tech_nodes``: 另有 ``prerequisites`` 前置科技名称列表

    另外还支持：
    - ``vehicles``（载具全部字段，含 ``price`` / 三类载货上限 / 百公里油耗）
    - ``cities``（仅「城市点位」节点，字段同 map_nodes）
    - ``companies``（按公司名取 ``industry`` 产业 key）

    覆盖合同清单可引用的十二张表：``materials`` / ``parts`` / ``products`` / ``map_nodes`` /
    ``cities`` / ``vehicles`` / ``companies`` / ``fuels`` / ``tech_nodes`` / ``infrastructures`` /
    ``warehouses`` / ``production_lines``。
    """
    from decimal import Decimal

    from apps.competition.basedata import models as basedata

    def as_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def origin_list(value):
        """产地：老数据是 JSON 数组字符串，新数据可能直接是列表/逗号分隔。"""
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [part.strip() for part in str(value).split(',') if part.strip()]

    def dict_map(value):
        """JSON 对象字符串 → dict（节点价格这类老数据）。"""
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value or '{}')
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def rows_of(model, **filters) -> dict:
        """整表序列化：名称 → 全部具体字段（跳过 id/时间戳/名称本身），外键取关联名称。"""
        skip = {'id', 'created_at', 'updated_at', 'name'}
        fields = [
            field for field in model._meta.concrete_fields
            if field.name not in skip
        ]
        out = {}
        for obj in model.objects.filter(**filters):
            row = {}
            for field in fields:
                if field.is_relation:
                    related = getattr(obj, field.name, None)
                    row[field.name] = str(related) if related is not None else ''
                    continue
                value = getattr(obj, field.attname)
                if isinstance(value, Decimal):
                    value = as_float(value)
                row[field.name] = value
            out[str(obj.name)] = row
        return out

    table = str(table or '').strip().lower()
    details: dict = {}

    if table == 'materials':
        details = rows_of(basedata.Material)
        for name, row in details.items():
            row['origin'] = origin_list(row.get('origin'))
            row['node_prices'] = dict_map(row.get('node_prices'))
            row['carbon_emission_coefficient'] = as_float(
                row.get('carbon_emission_coefficient'))
    elif table == 'parts':
        details = rows_of(basedata.Part)
        for row in details.values():
            row['materials'] = {}
        for part, material, ratio in basedata.PartMaterial.objects.values_list(
                'part__name', 'material__name', 'ratio'):
            details.setdefault(str(part), {'materials': {}})
            details[str(part)]['materials'][str(material)] = as_float(ratio)
    elif table == 'products':
        details = rows_of(basedata.Product)
        for row in details.values():
            row['parts'] = {}
        for product, part, ratio in basedata.ProductPart.objects.values_list(
                'product__name', 'part__name', 'ratio'):
            details.setdefault(str(product), {'parts': {}})
            details[str(product)]['parts'][str(part)] = as_float(ratio)
    elif table == 'map_nodes':
        details = rows_of(basedata.MapNode)
        for row in details.values():
            row['region'] = row.get('region') or ''
            row['city'] = row.get('city') or ''
    elif table == 'fuels':
        details = rows_of(basedata.Fuel)
        for row in details.values():
            row['price_per_liter'] = as_float(row.get('price_per_liter'))
    elif table == 'tech_nodes':
        details = rows_of(basedata.TechNode)
        for row in details.values():
            row['description'] = row.get('description') or ''
            row['research_cost'] = as_float(row.get('research_cost'))
            row['prerequisites'] = []
        for node, prerequisite in basedata.TechPrerequisite.objects.values_list(
                'node__name', 'prerequisite__name'):
            details.setdefault(str(node), {'prerequisites': []})
            details[str(node)]['prerequisites'].append(str(prerequisite))
    elif table == 'infrastructures':
        details = rows_of(basedata.Infrastructure)
    elif table == 'warehouses':
        details = rows_of(basedata.Warehouse)
        for row in details.values():
            row['capacity'] = as_float(row.get('capacity'))
            row['price'] = as_float(row.get('price'))
            row['type'] = row.get('type') or ''
    elif table == 'production_lines':
        details = rows_of(basedata.ProductionLine)
        for row in details.values():
            row['price'] = as_float(row.get('price'))
            row['labor_count'] = as_float(row.get('labor_count'))
            row['max_per_year'] = as_float(row.get('max_per_year'))
    elif table == 'vehicles':
        details = rows_of(basedata.Vehicle)
        for row in details.values():
            row['price'] = as_float(row.get('price'))
    elif table == 'cities':
        # 只取「城市点位」节点（排除矿点/车站/路网顶点）
        details = rows_of(basedata.MapNode, node_type__name='城市点位')
        for row in details.values():
            row['region'] = row.get('region') or ''
            row['city'] = row.get('city') or ''
    elif table == 'companies':
        from apps.competition.companies.models import Company

        for name, industry in Company.objects.values_list('name', 'industry_key'):
            details[str(name)] = {'industry': industry or ''}

    return details


def material_region_prices(regions: dict | None = None) -> dict:
    """原料「按地点价格」→ ``{原料: {区域: 参考价}}``（ctx.material_price 的数据源）。

    ``Material.node_prices`` 是 ``{地图节点 ID: 价格}``：建库时按城市点位建条目、
    价格先留空（0）。这里把每个节点的价格换算成它**所在区域**的价格：

    - 同一区域有多个城市时取算术平均；
    - 空价 / 非数字（<=0）视为「还没填价」，不参与平均；
    - 没有区域归属的节点直接跳过。
    """
    from apps.competition.basedata.models import Material

    region_of = regions if regions is not None else node_maps()['region']
    prices = {}
    for name, raw in Material.objects.values_list('name', 'node_prices'):
        try:
            node_prices = json.loads(raw or '{}')
        except (TypeError, ValueError):
            continue
        if not isinstance(node_prices, dict):
            continue
        by_region = {}
        for node_id, value in node_prices.items():
            region = region_of.get(f'#{str(node_id).strip().lstrip("#")}')
            if not region:
                continue
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            by_region.setdefault(region, []).append(price)
        if by_region:
            prices[str(name or '').strip()] = {
                region: round(sum(values) / len(values), 4)
                for region, values in by_region.items()
            }
    return prices


def build_context(contract: Contract, *, basis=None):
    """构造插件 ctx（§8.1：参与方解析、输入参数、公司字段读取，不暴露 ORM）。

    批量预取（消 N+1）：产业字段全表一次、参与方公司字段值一次，
    取值优先级与 ``_read_value`` 完全一致（精确财年 → 最新财年 → 无财年行 → 0）。
    """
    from plugins_runtime.api import ContractContext

    companies = party_company_map(contract)
    fiscal_year = contract.fiscal_year
    field_keys = set()
    if companies:
        field_keys = set(IndustryField.objects.values_list('field_key', flat=True))

    rows_by_key = {}
    if companies:
        for row in (CompanyFieldValue.objects
                    .filter(company__in=list(companies.values()))
                    .select_related('fiscal_year')):
            rows_by_key.setdefault((row.company_id, row.field_key), []).append(row)

    keys_by_company = {}
    for company_id, key in rows_by_key:
        keys_by_company.setdefault(company_id, set()).add(key)

    fields = {}
    for role, company in companies.items():
        keys = field_keys | keys_by_company.get(company.id, set())
        for key in keys:
            if basis is not None:
                fields[(role, key)] = _basis_value(company, key, basis)
            else:
                fields[(role, key)] = _pick_value(
                    rows_by_key.get((company.id, key), []), fiscal_year)

    maps = node_maps()
    return ContractContext(
        parties={role: company.name for role, company in companies.items()},
        inputs=contract.inputs or {},
        fields=fields,
        industries={role: company.industry_key for role, company in companies.items()},
        # 城市节点 → 区域名 / 任意节点 → 城市：插件据此把导入的数据换成区域或城市
        node_regions=maps['region'],
        node_cities=maps['city'],
        # 原料按地点价格 → 区域参考价：原料采购类插件用 ctx.material_price 查价
        material_prices=material_region_prices(maps['region']),
        # 基础数据条目的数值（价格/容量/用工数/前置科技…）：ctx.item_detail 按需查询
        item_detail_provider=basedata_item_details,
    )


def _call_plugin(fn, context, label: str):
    """调用插件函数：任何异常都转成业务错误，避免以 500 形式冒出去。"""
    try:
        return fn(context)
    except ContractError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 插件异常统一转业务错误（§5.4）
        raise ContractError(
            f'合同插件执行失败（{label}）：{type(exc).__name__}: {exc}') from exc


def run_check_ex(module, contract: Contract, *, basis=None) -> tuple:
    """运行 check 并附带**检查依据快照**（当时字段值，供账本重演替换展示）。"""
    context = build_context(contract, basis=basis)
    problems = _call_plugin(module.check, context, 'check')
    problems = [str(p) for p in (problems or [])]
    snapshot = {}
    for (role, field), value in getattr(context, '_fields', {}).items():
        snapshot.setdefault(role, {})[field] = value
    return problems, snapshot


def record_check(contract: Contract, checkpoint: str, problems: list, *, user=None,
                 round_no=None, basis=None):
    """检查结果落库留痕（append-only，界面按轮次回放当时的检查内容）。

    round_no 可显式指定（回滚后补记失败留痕时与合同轮次不同）。
    """
    from apps.competition.contracts.models import ContractCheck

    return ContractCheck.objects.create(
        contract=contract,
        round_no=contract.round_no if round_no is None else round_no,
        checkpoint=checkpoint,
        problems=list(problems or []),
        passed=not problems,
        basis=basis or {},
        checked_by=getattr(user, 'id', None),
        checked_by_username=getattr(user, 'username', ''),
    )


def run_apply(module, contract: Contract, *, basis=None) -> list:
    context = build_context(contract, basis=basis)
    effects = _call_plugin(module.apply, context, 'apply') or []
    return list(effects)


# 兼容旧引用（tests_engine）：算子计算统一在 contracts.values.effect_after
_effect_after = effect_after


def _write_value(company, field_key, value, fiscal_year):
    """写字段值（财报按财年行、实体信息表按无财年行，乐观锁 version+1）；fiscal_year=None 时财报取最新财年行。"""
    definition = IndustryField.objects.filter(field_key=field_key).first()
    if definition and definition.data_table == IndustryField.DataTable.FINANCE:
        if fiscal_year is not None:
            target_fy = fiscal_year
        else:
            latest = (
                CompanyFieldValue.objects
                .filter(company=company, field_key=field_key, fiscal_year__isnull=False)
                .order_by('-fiscal_year__year')
                .first()
            )
            target_fy = latest.fiscal_year if latest else None
    else:
        target_fy = None
    row, _created = CompanyFieldValue.objects.get_or_create(
        company=company, field_key=field_key, fiscal_year=target_fy,
        defaults={'value': value, 'version': 1},
    )
    if not _created:
        row.value = value
        row.version += 1
        row.save(update_fields=['value', 'version', 'updated_at'])
    return row


def apply_effects(contract: Contract, effects, *, source, operator, basis=None):
    """落账引擎（§7.2）：单事务内读当前值 → 计算后值 → 写字段值 + 不可变审计 + 字段日志。

    效果目标有两种：公司字段（默认）与**区域字段**（``effect.region`` 非空）。
    区域字段落账前先校验该字段配置的修改条件（针对发起效果的公司）。

    补录（``basis`` 非空）时：
    - 同一合同内多个效果按内存叠加计算（不依赖已写库值）；
    - **财年计时器实体字段**（如产能/开采上限）只写历史审计，不回写当前值，
      否则会把所补录财年的结果污染到当前财年（当前值已由 FY 计时器重置）。
    """
    companies = party_company_map(contract)
    fiscal_year = contract.fiscal_year
    effects = list(effects)
    effect_fields = {e.field for e in effects if not getattr(e, 'region', '')}
    definitions = {
        f.field_key: f
        for f in IndustryField.objects.filter(field_key__in=effect_fields)
    }
    overrides = {}
    for effect in effects:
        if getattr(effect, 'region', ''):
            apply_region_effect(
                contract, effect, companies, source=source, operator=operator)
            continue
        company = resolve_effect_company(effect, companies)
        key = (company.id, effect.field)
        if basis is not None:
            before = overrides[key] if key in overrides else _basis_value(
                company, effect.field, basis)
        else:
            before = _read_value(company, effect.field, fiscal_year)
        after = effect_after(before, effect.op, effect.value)

        if basis is not None:
            overrides[key] = after
            definition = definitions.get(effect.field)
            skip_timer_entity = bool(
                definition
                and definition.data_table == IndustryField.DataTable.ENTITY
                and definition.timer_enabled
            )
            if not skip_timer_entity:
                _write_value(company, effect.field, after, fiscal_year)
        else:
            _write_value(company, effect.field, after, fiscal_year)

        ContractFieldEffect.objects.create(
            contract=contract, company=company, field_key=effect.field,
            op=effect.op, value_raw=effect.value,
            before_raw=before, after_raw=after, round_no=contract.round_no,
        )
        write_field_log(
            company=company, field_key=effect.field, op=effect.op,
            before=before, after=after, source=source, contract=contract,
            round_no=contract.round_no, operator=operator,
        )


def rollback_round(contract: Contract, *, operator, round_no=None):
    """回滚旧落账 = 按效果审计逆序重放（§3.4 修改 = 回滚 + 重做）。"""
    fiscal_year = contract.fiscal_year
    target_round = contract.round_no if round_no is None else round_no
    effects = list(contract.effects.filter(round_no=target_round).order_by('-created_at', '-id'))
    from apps.competition.regions.services import read_region_value, write_region_value

    for effect in effects:
        from apps.competition.companies.models import Company
        company = Company.objects.filter(pk=effect.company_id).first()
        if effect.region_id:
            # 区域字段效果：回滚区域值（SET 恢复落账前快照）
            region = effect.region
            if region is None:
                continue
            before = read_region_value(region.id, effect.field_key)
            after, inverse_op = ops.inverse_apply(
                before, effect.op, effect.value_raw, effect.before_raw)
            write_region_value(region.id, effect.field_key, after)
            write_field_log(
                company=company, region=region, field_key=effect.field_key, op=inverse_op,
                before=before, after=after, source=FieldLog.Source.CONTRACT_ROLLBACK,
                contract=contract, round_no=contract.round_no, operator=operator,
            )
            continue
        if company is None:
            continue
        before = _read_value(company, effect.field_key, fiscal_year)
        after, inverse_op = ops.inverse_apply(
            before, effect.op, effect.value_raw, effect.before_raw)
        _write_value(company, effect.field_key, after, fiscal_year)
        write_field_log(
            company=company, field_key=effect.field_key, op=inverse_op,
            before=before, after=after, source=FieldLog.Source.CONTRACT_ROLLBACK,
            contract=contract, round_no=contract.round_no, operator=operator,
        )

    # 回滚同样要重算：否则公式字段会停留在回滚前的值
    recompute_contract_companies(
        contract, operator=operator, log_source=FieldLog.Source.CONTRACT_ROLLBACK)


def generate_unified_number(contract: Contract, competition) -> str:
    """统一编号：比赛代码-FY财年-5位自增流水（如 49-FY0-00001）。"""
    comp_code = competition.code or str(competition.id)
    fy_part = f'FY{contract.fiscal_year.year}' if contract.fiscal_year_id else 'FY0'
    # 序列键 = 比赛 ID + 财年：比赛代码可被管理员改，用 ID 才不会改一次就重号
    seq_key = f'cid{competition.id}-{fy_part}'
    with comp_atomic():
        seq, _ = NumberSequence.objects.select_for_update().get_or_create(
            key=seq_key, defaults={'last_value': 0})
        seq.last_value += 1
        seq.save(update_fields=['last_value'])
    return f'{comp_code}-{fy_part}-{seq.last_value:05d}'


ALL_FIELDS = '*'  # ContractFreeze.field_key 哨兵：整公司全部资源

# 审批超时提醒（2026-11）：修改申请/补录审核超过这个时长仍未处理就催办
OVERDUE_HOURS = settings.CONTRACT_OVERDUE_HOURS
OVERDUE_STATUSES = ('MOD_APPLYING', 'BACKFILL_REVIEW')


def is_overdue(contract: Contract, *, now=None) -> bool:
    """待审批单据是否已超过 OVERDUE_HOURS 未处理。"""
    from datetime import timedelta

    if contract.status not in OVERDUE_STATUSES:
        return False
    now = now or timezone.now()
    return contract.updated_at <= now - timedelta(hours=OVERDUE_HOURS)


def notify_overdue(contract: Contract, *, now=None) -> int:
    """给超管与申请方发超时催办；同一单据只催一次（记 overdue_notified_at）。"""
    from apps.competition.messages.services import send_message

    if not is_overdue(contract, now=now):
        return 0
    if contract.overdue_notified_at is not None:
        return 0

    label = contract.unified_number or contract.name or f'合同 #{contract.id}'
    kind_label = '修改申请' if contract.status == 'MOD_APPLYING' else '补录审核'
    hours = OVERDUE_HOURS

    # 催办超管
    from apps.common.authority import competition_super_admin_ids

    sent = 0
    for uid in competition_super_admin_ids() or []:
        send_message(
            uid, kind='CONTRACT_OVERDUE',
            title=f'合同 {label} 的{kind_label}已超过 {hours} 小时未处理',
            body='请尽快审批；超时不影响系统运行，但会阻塞参与方后续操作。',
            payload={'contractId': contract.id, 'status': contract.status},
        )
        sent += 1

    # 提示申请方：还在排队
    applicant_id = None
    mod = contract.mod_requests.filter(
        status=ContractModRequest.Status.APPLYING).first()
    if mod is not None:
        applicant_id = mod.requested_by
    applicant_id = applicant_id or contract.created_by
    if applicant_id:
        send_message(
            applicant_id, kind='CONTRACT_OVERDUE_WAIT',
            title=f'合同 {label} 的{kind_label}仍在审核中',
            body=f'已超过 {hours} 小时未处理，已提醒超级管理员，请耐心等待。',
            payload={'contractId': contract.id},
        )
        sent += 1

    contract.overdue_notified_at = timezone.now()
    # 只写催办时间：不要动 updated_at，否则单据会看起来「刚更新过」，超时判断与排序都会被带偏
    contract.save(update_fields=['overdue_notified_at'])
    return sent

# 冻结超时：合同修改流程挂住（超管没批也没驳）时，到期自动解冻，避免全公司停摆
FREEZE_TIMEOUT_HOURS = settings.CONTRACT_FREEZE_TIMEOUT_HOURS


def expire_stale_freezes() -> int:
    """把超时未处理的冻结标记为已解冻（写 reason 留痕），返回解冻条数。"""
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(hours=FREEZE_TIMEOUT_HOURS)
    return (ContractFreeze.objects
            .filter(unfrozen_at__isnull=True, frozen_at__lt=cutoff)
            .update(unfrozen_at=timezone.now(),
                    reason=f'修改流程超过 {FREEZE_TIMEOUT_HOURS} 小时未处理，自动解冻'))


def freeze_contract(contract: Contract):
    """合同进入修改流程：冻结参与方公司的**全部资源**（哨兵 ``field_key='*'``）。

    2026-11 口径：落账本身不再冻结；冻结只覆盖"该合同修改期间"，
    修改完成或被驳回时由 ``unfreeze_contract`` 解除。
    """
    label = contract.unified_number or contract.id
    companies = {p.get('companyId') for p in contract.parties if p.get('companyId')}
    for company_id in companies:
        ContractFreeze.objects.get_or_create(
            contract=contract, company_id=company_id, field_key=ALL_FIELDS,
            defaults={'reason': f'合同 {label} 修改中，资源冻结'},
        )


def unfreeze_contract(contract: Contract, reason: str = ''):
    now = timezone.now()
    contract.freezes.filter(unfrozen_at__isnull=True).update(unfrozen_at=now, reason=reason[:200])


def assert_field_writable(company_id, field_key):
    """手工/非合同写入路径守卫：公司有合同正在修改时，全部资源禁止修改（§7.4）。

    冻结是**整公司**的：只要存在未解除的冻结行（``field_key='*'`` 或该字段本身），
    就说明该公司有合同处于修改流程中，等修改完成/驳回解冻后才能手工修改。
    """
    expire_stale_freezes()
    freeze = (
        ContractFreeze.objects
        .filter(company_id=company_id, field_key__in=[field_key, ALL_FIELDS],
                unfrozen_at__isnull=True)
        .select_related('contract')
        .first()
    )
    if freeze is not None:
        label = freeze.contract.unified_number or freeze.contract.id
        raise ContractError(
            f'公司有合同正在修改（合同 {label}），资源已冻结，暂不能修改字段 {field_key}'
        )


def _assert_no_active_modification(contract: Contract):
    """其他合同执行守卫：参与方公司有进行中的合同修改时，该合同不能落账。"""
    company_ids = {p.get('companyId') for p in contract.parties if p.get('companyId')}
    if not company_ids:
        return
    expire_stale_freezes()
    blocker = (
        ContractFreeze.objects
        .filter(company_id__in=company_ids, field_key=ALL_FIELDS, unfrozen_at__isnull=True)
        .exclude(contract=contract)
        .select_related('contract')
        .first()
    )
    if blocker is not None:
        label = blocker.contract.unified_number or blocker.contract.id
        raise ContractError(
            f'参与方公司有合同正在修改（合同 {label}），资源冻结中，暂不能执行该合同'
        )


def _competition():
    from apps.global_.competitions.models import Competition
    return Competition.objects.get(pk=ctx.get_competition_id())


def create_contract(*, contract_type_key, plugin_version, name, parties, inputs,
                    user, is_backfill=False, fiscal_year=None):
    """T1：创建合同草稿（参与方与输入满足 inputSchema）。"""
    module = load_contract_module_simple(contract_type_key, plugin_version)
    parties = [dict(p, confirmOrder=i) for i, p in enumerate(parties)]
    problems = _validate_inputs(module, parties, inputs)
    if problems:
        raise ContractError('；'.join(problems))
    if fiscal_year is None and not is_backfill:
        # 默认挂当前进行中的财年（财务报表按财年行记录）
        from apps.competition.fiscal.models import FiscalYear
        fiscal_year = FiscalYear.objects.filter(status=FiscalYear.Status.OPEN).first()
    return Contract.objects.create(
        contract_type_key=contract_type_key,
        plugin_version=plugin_version,
        name=name or '',
        status=Contract.Status.BACKFILL_REVIEW if is_backfill else Contract.Status.DRAFT,
        parties=parties,
        inputs=inputs,
        is_backfill=is_backfill,
        fiscal_year=fiscal_year,
        created_by=user.id,
    )


def load_contract_module_simple(contract_type_key, plugin_version):
    from apps.competition.contracts.services import contract_module_for
    return contract_module_for(contract_type_key, plugin_version)


LIST_PREFIX = 'LIST'
LIST_ITEM_KEY = 'item'


def _ref_exists(table: str, value) -> bool:
    """LIST 行里的引用是否真的存在于基础数据（按名称或编码）。"""
    text = str(value or '').strip()
    if not text:
        return False
    try:
        if table == 'materials':
            from apps.competition.basedata.models import Material

            return Material.objects.filter(name=text).exists()
        if table == 'products':
            from apps.competition.basedata.models import Product

            return Product.objects.filter(name=text).exists()
        if table == 'parts':
            from apps.competition.basedata.models import Part

            return Part.objects.filter(name=text).exists()
        if table == 'map_nodes':
            from apps.competition.basedata.models import MapNode

            return MapNode.objects.filter(name=text).exists()
        if table == 'fuels':
            from apps.competition.basedata.models import Fuel

            return Fuel.objects.filter(name=text).exists()
        if table == 'tech_nodes':
            from apps.competition.basedata.models import TechNode

            return TechNode.objects.filter(name=text).exists()
        if table == 'infrastructures':
            from apps.competition.basedata.models import Infrastructure

            return Infrastructure.objects.filter(name=text).exists()
        if table == 'warehouses':
            from apps.competition.basedata.models import Warehouse

            return Warehouse.objects.filter(name=text).exists()
        if table == 'production_lines':
            from apps.competition.basedata.models import ProductionLine

            return ProductionLine.objects.filter(name=text).exists()
        if table == 'vehicles':
            from apps.competition.basedata.models import Vehicle

            return Vehicle.objects.filter(name=text).exists()
        if table == 'cities':
            from apps.competition.basedata.models import MapNode

            return MapNode.objects.filter(name=text, node_type__name='城市点位').exists()
        if table == 'companies':
            from apps.competition.companies.models import Company

            return Company.objects.filter(name=text).exists()
        if table == 'regions':
            from apps.competition.basedata.models import MapNode
            from apps.competition.regions.models import Region

            return (Region.objects.filter(name=text).exists()
                    or MapNode.objects.filter(region=text).exists())
    except Exception:  # noqa: BLE001 —— 查不到时按「无法校验」放行，避免阻断业务
        return True
    return True


def _validate_list_input(schema, value) -> list:
    """LIST 类型输入（如原料清单）：行结构 + 引用存在性 + 每行字段校验。

    ``optional=True`` 的清单允许整项留空（一行都没有），用于「多清单任选」的合同。
    """
    label = schema.get('label') or schema.get('key')
    rows = value if isinstance(value, list) else None
    if not rows:
        return [] if schema.get('optional') else [f'缺少输入项 {label}']
    problems = []
    min_items = schema.get('minItems')
    if min_items is not None and len(rows) < int(min_items):
        problems.append(f'{label} 至少需要 {min_items} 行')

    # 引用表：优先 itemType，其次从 type（LIST:materials）里取
    raw_type = str(schema.get('type') or '')
    item_type = str(schema.get('itemType') or '').upper()
    if not item_type and ':' in raw_type:
        item_type = raw_type.split(':', 1)[1].strip().upper()
    table = item_type.split(':', 1)[-1].strip().lower() if item_type else ''
    item_label = schema.get('itemLabel') or '原料'
    fields = list(schema.get('fields') or [])

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            problems.append(f'{label} 第 {index} 行格式不正确')
            continue
        item = row.get(LIST_ITEM_KEY)
        if not str(item or '').strip():
            problems.append(f'{label} 第 {index} 行缺少{item_label}')
            continue
        if table and not _ref_exists(table, item):
            problems.append(f'{label} 第 {index} 行的{item_label}「{item}」不存在')
        for field in fields:
            key = field.get('key')
            field_label = field.get('label') or key
            cell = row.get(key)
            if cell is None or str(cell).strip() == '':
                problems.append(f'{label} 第 {index} 行缺少{field_label}')
                continue
            if str(field.get('type') or '').upper().startswith('NUMBER'):
                try:
                    number = float(cell)
                except (TypeError, ValueError):
                    problems.append(f'{label} 第 {index} 行的{field_label}不是数字')
                    continue
                if field.get('min') is not None and number < float(field['min']):
                    problems.append(
                        f'{label} 第 {index} 行的{field_label}小于最小值 {field["min"]}')
    return problems


def _validate_inputs(module, parties, inputs) -> list:
    problems = []
    known_roles = {p['role']: p for p in module.PARTY_ROLES}
    seen_roles = set()
    for p in parties:
        role = p.get('role')
        if role not in known_roles:
            problems.append(f'未知参与方角色 {role}')
        elif role in seen_roles:
            problems.append(f'参与方角色重复 {role}')
        elif not p.get('companyId'):
            problems.append(f'参与方 {role} 缺少公司')
        seen_roles.add(role)
    for s in module.INPUT_SCHEMA:
        value = (inputs or {}).get(s['key'])
        if str(s.get('type') or '').upper().startswith(LIST_PREFIX):
            problems.extend(_validate_list_input(s, value))
            continue
        if isinstance(value, str):
            value = value.strip()
        # REF:<表> 输入项：填的是条目名称，提交前校验存在（以前只校验非空）
        raw_type = str(s.get('type') or '')
        if raw_type.upper().startswith('REF') and value not in (None, ''):
            table = raw_type.split(':', 1)[1].strip().lower() if ':' in raw_type else ''
            if table and not _ref_exists(table, value):
                problems.append(
                    f'输入项「{s.get("label") or s["key"]}」的取值「{value}」不存在')
                continue
        # 2026-11 决策：合同输入项一律必填，不再区分 required/min
        if s.get('type') == 'BOOLEAN':
            if value is None:
                problems.append(f'缺少输入项 {s.get("label") or s["key"]}')
        elif value in (None, '') or value == [] or value == {}:
            problems.append(f'缺少输入项 {s.get("label") or s["key"]}')
        if s.get('min') is not None:
            try:
                if float(value) < float(s['min']):
                    problems.append(f'{s.get("label") or s["key"]} 小于最小值 {s["min"]}')
            except (TypeError, ValueError):
                pass
    return problems


def submit_contract(contract: Contract, *, user):
    """T2：提交草稿（事务内锁合同行，防重复提交）。"""
    return run_locked(contract, lambda c: _submit_contract(c, user=user))


def _submit_contract(contract: Contract, *, user):
    """T2：提交草稿，运行 check()（保证创建即能执行）。"""
    if contract.status != Contract.Status.DRAFT:
        raise ContractError(f'当前状态 {contract.status} 不允许提交')
    module = load_contract_module(contract)
    basis = None
    if contract.is_backfill:
        # 补录检查必须用「所补录财年末备份快照」，不能用当前值（当前值可能已被财年计时器重置）
        basis = _contract_basis(contract)
    problems, check_basis = run_check_ex(module, contract, basis=basis)
    record_check(contract, 'SUBMIT', problems, user=user, basis=check_basis)  # 检查内容+依据落库
    if problems:
        raise CheckFailedError('检查未通过：' + '；'.join(problems))
    contract.status = Contract.Status.PENDING_PARTY
    contract.pending_party_index = 0
    contract.save(update_fields=['status', 'pending_party_index', 'updated_at'])
    _notify_pending_party(contract)
    return contract


def confirm_party(contract: Contract, *, user, party_role=None):
    """T3/T4：参与方按顺序确认（事务内锁合同行，防双击重复确认）。"""
    return run_locked(
        contract, lambda c: _confirm_party(c, user=user, party_role=party_role))


def _confirm_party(contract: Contract, *, user, party_role=None):
    """T3：参与方按顺序确认；T4：确认链完成 → 生成统一编号并自动执行。"""
    if contract.status != Contract.Status.PENDING_PARTY:
        raise ContractError(f'当前状态 {contract.status} 不允许确认')
    index = contract.pending_party_index
    parties = sorted(contract.parties, key=lambda p: p.get('confirmOrder', 0))
    if index >= len(parties):
        raise ContractError('确认链已结束')
    current = parties[index]
    if party_role and party_role != current['role']:
        raise ContractError(f'当前等待 {current["role"]} 确认，不能由 {party_role} 确认')

    snapshot = ctx.get_device_snapshot() or {}
    ContractConfirmation.objects.create(
        contract=contract,
        party_role=current['role'],
        company_id=current.get('companyId'),
        confirmed_by=user.id,
        confirmed_by_username=user.username,
        confirmed_at=timezone.now(),
        device_snapshot=snapshot,
        ip=snapshot.get('ip'),
        trace_id=ctx.get_trace_id() or '',
    )
    current['confirmAt'] = timezone.now().isoformat()
    current['confirmedBy'] = user.username
    contract.parties = parties
    contract.pending_party_index = index + 1

    if index + 1 < len(parties):
        contract.status = Contract.Status.PENDING_PARTY
        contract.save(update_fields=['parties', 'pending_party_index', 'status', 'updated_at'])
        _notify_pending_party(contract)
        return contract

    contract.status = Contract.Status.PENDING_EXEC
    contract.save(update_fields=['parties', 'pending_party_index', 'status', 'updated_at'])
    _auto_number_and_execute(contract)
    return contract


def reject_party(contract: Contract, *, user, reason: str = ''):
    """T3'：任一方拒绝确认 → 退回草稿（事务内锁合同行）。"""
    return run_locked(contract, lambda c: _reject_party(c, user=user, reason=reason))


def _reject_party(contract: Contract, *, user, reason: str = ''):
    """T3'：任一参与方拒绝确认 → 退回草稿，发起方可修改后重新提交。

    与确认相对的出口：合同停在待确认时，任一方都能表态；拒绝后清空整条确认链，
    并把拒绝人/原因记在参与方 JSON 上（详情页时间线可追溯）。
    """
    from apps.common.authority import can_act_for_company

    if contract.status != Contract.Status.PENDING_PARTY:
        raise ContractError(f'当前状态 {contract.status} 不允许拒绝确认')
    my_parties = [
        p for p in (contract.parties or [])
        if p.get('companyId') and can_act_for_company(user, p.get('companyId'))
    ]
    if not my_parties:
        raise ContractPermissionError('只有参与方公司的成员可以拒绝确认')

    party = my_parties[0]
    parties = [dict(p) for p in (contract.parties or [])]
    for entry in parties:
        entry.pop('confirmAt', None)
        entry.pop('confirmedBy', None)
        if entry.get('role') == party.get('role'):
            entry['rejectedAt'] = timezone.now().isoformat()
            entry['rejectedBy'] = user.username
            entry['rejectReason'] = reason or ''

    contract.parties = parties
    contract.status = Contract.Status.DRAFT
    contract.pending_party_index = 0
    contract.save(update_fields=['parties', 'status', 'pending_party_index', 'updated_at'])

    from apps.competition.messages.services import send_message

    label = contract.unified_number or (contract.name or f'合同 #{contract.id}')
    send_message(
        contract.created_by, kind='CONTRACT_REJECTED',
        title=f'合同 {label} 被拒绝确认',
        body=f'{user.username}（{party.get("role")}）拒绝确认：{reason or "未填写原因"}；'
             f'合同已退回草稿，可修改后重新提交',
        payload={'contractId': contract.id},
    )
    return contract


def update_draft(contract: Contract, *, user, name=None, parties=None, inputs=None):
    """草稿编辑（事务内锁合同行）。"""
    return run_locked(
        contract,
        lambda c: _update_draft(c, user=user, name=name, parties=parties, inputs=inputs))


def _update_draft(contract: Contract, *, user, name=None, parties=None, inputs=None):
    """草稿编辑（拒绝后重提的配套入口）：只有草稿态可改，且校验输入项与参与方。"""
    if contract.status != Contract.Status.DRAFT:
        raise ContractError(f'当前状态 {contract.status} 不允许编辑，只有草稿可以修改')
    module = load_contract_module(contract)
    new_parties = [dict(p, confirmOrder=i) for i, p in enumerate(
        parties if parties is not None else contract.parties or [])]
    for entry in new_parties:
        entry.pop('rejectedAt', None)
        entry.pop('rejectedBy', None)
        entry.pop('rejectReason', None)
    new_inputs = inputs if inputs is not None else (contract.inputs or {})
    problems = _validate_inputs(module, new_parties, new_inputs)
    if problems:
        raise ContractError('；'.join(problems))

    update_fields = ['inputs', 'parties', 'updated_at']
    contract.inputs = new_inputs
    contract.parties = new_parties
    if name is not None:
        contract.name = str(name)[:200]
        update_fields.append('name')
    contract.save(update_fields=update_fields)
    return contract


def _auto_number_and_execute(contract: Contract):
    """编号补完后自动执行（T4/T5/T10）：编号 → 执行 → 再次检查 → 落账。"""
    competition = _competition()
    if not contract.unified_number:
        contract.unified_number = generate_unified_number(contract, competition)
        contract.numbered_at = timezone.now()
        contract.save(update_fields=['unified_number', 'numbered_at', 'updated_at'])
    try:
        execute_and_post(contract)
    except ContractError as exc:
        contract.status = Contract.Status.EXEC_FAILED
        contract.save(update_fields=['status', 'updated_at'])
        from apps.competition.messages.services import send_message
        send_message(
            contract.created_by, kind='CONTRACT_EXEC_FAILED',
            title=f'合同 {contract.unified_number} 自动执行失败',
            body=str(exc), payload={'contractId': contract.id},
        )
        raise


def _assert_backfill_backup(contract: Contract):
    from apps.competition.fiscal.models import FiscalYearBackup

    if not FiscalYearBackup.objects.filter(fiscal_year_id=contract.fiscal_year_id).exists():
        raise ContractError('缺少财年末备份快照，无法执行补录')


def retry_execute(contract: Contract, *, user):
    """EXEC_FAILED → 重试执行：不重新生成统一编号（编号已存在），重跑 execute_and_post。"""

    def _impl(locked: Contract):
        if locked.status != Contract.Status.EXEC_FAILED:
            raise ContractError(f'当前状态 {locked.status} 不允许重试执行')
        locked.status = Contract.Status.PENDING_EXEC
        locked.save(update_fields=['status', 'updated_at'])
        return execute_and_post(locked, operator=user)

    return run_locked(contract, _impl)


def _execute(contract: Contract, *, operator, source: str, recheck_error: str):
    """执行 = apply 改写 + 再次检查 + 落账（须在调用方事务内执行，§7.5）。

    ``recheck_error`` 为再次检查未通过时的错误前缀（首落账 / 修改后重落账文案不同）。
    """
    _assert_no_active_modification(contract)
    if contract.is_backfill:
        _assert_backfill_backup(contract)
    module = load_contract_module(contract)
    basis = None
    if contract.is_backfill and contract.fiscal_year_id:
        basis = _contract_basis(contract)

    effects = run_apply(module, contract, basis=basis)
    contract.status = Contract.Status.EXECUTED
    contract.executed_at = timezone.now()
    contract.save(update_fields=['status', 'executed_at', 'updated_at'])

    problems, check_basis = run_check_ex(module, contract, basis=basis)
    record_check(contract, 'RECHECK', problems, user=operator, basis=check_basis)
    if problems:
        raise CheckFailedError(recheck_error + '；'.join(problems))

    apply_effects(contract, effects, source=source, operator=operator, basis=basis)
    if contract.is_backfill:
        _backfill_sync(contract, effects, operator)
    # 落账即重算公式字段：派生值（如贷款额度=现金×0.5）不用等财年定时器
    recompute_after_post(contract, operator=operator)

    contract.status = Contract.Status.POSTED
    contract.posted_at = timezone.now()
    contract.save(update_fields=['status', 'posted_at', 'updated_at'])


def execute_and_post(contract: Contract, *, operator=None):
    """PENDING_EXEC → EXECUTED(apply) → 再次检查 → POSTED(落账)；整体一个事务，失败不落半账（§7.5）。"""
    source = FieldLog.Source.CONTRACT_REPOST if contract.round_no else FieldLog.Source.CONTRACT_POST
    operator = operator or _actor(contract)
    original = contract  # 调用方持有的实例：执行完把最新状态同步回去
    try:
        with comp_atomic():
            # 并发/重复点击防护：同一张合同同一时刻只允许一个执行流
            contract = lock_contract(contract)
            if contract.status != Contract.Status.PENDING_EXEC:
                raise ContractError(
                    f'当前状态 {contract.get_status_display()} 不允许执行（可能已落账）')
            _execute(contract, operator=operator, source=source,
                     recheck_error='落账前再次检查未通过：')
    except CheckFailedError as exc:
        # 检查失败 → 整个事务回滚（不落半账）；失败留痕在此补记（回滚会连带撤销库内记录）
        record_check(contract, 'RECHECK', [str(exc)], user=operator)
        raise
    finally:
        original.refresh_from_db()
    return contract


def _actor(contract: Contract):
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(pk=contract.created_by).first()


def _backup_basis(contract: Contract):
    from apps.competition.fiscal.models import FiscalYearBackup
    basis = {}
    for backup in FiscalYearBackup.objects.filter(fiscal_year_id=contract.fiscal_year_id):
        basis[backup.company_id] = backup.snapshot or {}
    return basis


def _contract_basis(contract: Contract):
    """补录合同的历史基准（所补录财年末快照）；非补录返回 None。

    同一财年可能有多张已落账的补录合同：快照是财年末的原始状态，需按时间顺序
    重放这些补录的历史效果，得到「截至当前」的有效历史基准（否则会重复使用同一份产能）。
    """
    if not (contract.is_backfill and contract.fiscal_year_id):
        return None
    _assert_backfill_backup(contract)
    basis = _backup_basis(contract)
    from django.db.models import F
    prior = (
        ContractFieldEffect.objects
        .filter(
            contract__is_backfill=True,
            contract__fiscal_year_id=contract.fiscal_year_id,
            contract__status=Contract.Status.POSTED,
            round_no=F('contract__round_no'),
            region__isnull=True,
        )
        .exclude(contract_id=contract.id)
        .order_by('contract__posted_at', 'contract__id', 'id')
    )
    for effect in prior:
        snap = basis.setdefault(effect.company_id, {})
        current = snap.get(effect.field_key, 0)
        snap[effect.field_key] = effect_after(current, effect.op, effect.value_raw)
    return basis


def _backfill_sync(contract: Contract, effects, operator):
    """补录落账后：非财年定时器字段自动同步到当前数据（§2.2 阶段五 / BACKFILL_SYNC）；财年定时器字段不向后同步。"""
    companies = party_company_map(contract)
    timer_keys = set(IndustryField.objects.filter(timer_enabled=True)
                     .values_list('field_key', flat=True))
    for effect in effects:
        if getattr(effect, 'region', ''):
            continue  # 区域字段不参与财年定时器同步（只影响区域自身的值）
        if effect.field in timer_keys:
            continue
        definition = IndustryField.objects.filter(field_key=effect.field).first()
        if not definition or definition.data_table != IndustryField.DataTable.FINANCE:
            continue
        company = resolve_effect_company(effect, companies)
        current = _read_value(company, effect.field, None)
        after = effect_after(current, effect.op, effect.value)
        _write_base_value(company, effect.field, after)
        write_field_log(
            company=company, field_key=effect.field, op=effect.op,
            before=current, after=after, source=FieldLog.Source.BACKFILL_SYNC,
            contract=contract, round_no=contract.round_no, operator=operator,
        )


def terminate_contract(contract: Contract, *, user, reason: str = ''):
    """终止合同（2026-11）：回滚当前轮次恢复字段值 → 置已终止 → 解冻 → 通知各方。"""
    return run_locked(
        contract, lambda c: _terminate_contract(c, user=user, reason=reason))


def _terminate_contract(contract: Contract, *, user, reason: str = ''):
    if contract.status == Contract.Status.CANCELLED:
        raise ContractError('合同已终止，无需重复操作')
    if contract.status == Contract.Status.PENDING_EXEC:
        # 待执行还没落账，直接终止即可（不需要回滚）
        pass

    # 首轮落账的 round_no 是 0，不能拿它当真假判断，只看当前轮次有没有效果
    if contract.effects.filter(round_no=contract.round_no).exists():
        rollback_round(contract, operator=user, round_no=contract.round_no)
        rollback_backfill_sync(contract, operator=user)
    unfreeze_contract(contract, reason='合同终止，资源解冻')

    contract.status = Contract.Status.CANCELLED
    contract.cancelled_at = timezone.now()
    contract.cancelled_by_username = user.username
    contract.cancel_reason = (reason or '')[:200]
    contract.save(update_fields=['status', 'cancelled_at', 'cancelled_by_username',
                                 'cancel_reason', 'updated_at'])

    from apps.competition.messages.services import send_message

    label = contract.unified_number or contract.name or f'合同 #{contract.id}'
    recipients = {contract.created_by}
    if contract.created_by:
        recipients.discard(0)
    for company_id in {p.get('companyId') for p in contract.parties if p.get('companyId')}:
        from apps.common.authority import company_strict_actor_ids
        recipients |= company_strict_actor_ids(company_id)
    # 只给真实存在的账号发（历史导入合同的 created_by 可能是占位 ID）
    from django.contrib.auth import get_user_model

    existing = set(get_user_model().objects.filter(
        id__in=[u for u in recipients if u]).values_list('id', flat=True))
    for uid in sorted(existing):
        send_message(
            uid, kind='CONTRACT_TERMINATED',
            title=f'合同 {label} 已终止',
            body=f'{user.username} 终止了该合同：{reason or "未填写原因"}',
            payload={'contractId': contract.id},
        )
    return contract


def recompute_contract_companies(contract: Contract, *, operator=None, log_source=None):
    """重算合同涉及公司的公式字段，并在有变化时通知前端刷新公司页。

    补录是历史账，重算会用当前值口径污染历史，故不触发。
    """
    if contract.is_backfill:
        return 0
    from apps.common import context as ctx

    if ctx.get_competition_id() is None:
        # 没有比赛上下文（如账本重演/脚本直接调用）时跳过重算，避免越界访问比赛库
        return 0
    from apps.competition.companies.models import Company
    from apps.competition.industries.services import recompute_company_fields

    company_ids = {
        e.company_id for e in ContractFieldEffect.objects.filter(
            contract=contract, round_no=contract.round_no, region__isnull=True)
    }
    changed = 0
    for company_id in company_ids:
        company = Company.objects.filter(pk=company_id).first()
        if company is None:
            continue
        changed += recompute_company_fields(
            company, operator=operator,
            log_source=log_source or FieldLog.Source.CALC)
    if changed:
        from apps.common import context as ctx

        _notify_companies_changed(ctx.get_competition_id())
    return changed


def _notify_companies_changed(competition_id):
    """重算写在合同事务里：提交后再广播，避免前端读到未提交值。"""
    if not competition_id:
        return
    from django.db import transaction

    from apps.common.broadcast import emit_resource_changed

    transaction.on_commit(
        lambda: emit_resource_changed(
            competition_id, 'companies', 'updated', {'reason': 'recompute'}))


def recompute_after_post(contract: Contract, *, operator=None):
    """落账后重算受影响公司的公式字段（2026-11：不等财年定时器，落账即自洽）。"""
    return recompute_contract_companies(contract, operator=operator)


def rollback_backfill_sync(contract: Contract, *, operator):
    """撤回补录合同同步到「当前值」的部分（BACKFILL_SYNC 不是 effect，回滚轮次带不走它）。"""
    if not (contract.is_backfill and contract.fiscal_year_id):
        return 0
    timer_keys = set(
        IndustryField.objects.filter(timer_enabled=True).values_list('field_key', flat=True))
    effects = list(contract.effects.filter(round_no=contract.round_no))
    reverted = 0
    for effect in reversed(effects):
        if effect.region_id or effect.field_key in timer_keys:
            continue
        definition = IndustryField.objects.filter(field_key=effect.field_key).first()
        if definition is None or definition.data_table != IndustryField.DataTable.FINANCE:
            continue
        company = effect.company
        current = _read_value(company, effect.field_key, None)
        after, inverse_op = ops.inverse_apply(
            current, effect.op, effect.value_raw, effect.before_raw)
        _write_base_value(company, effect.field_key, after)
        write_field_log(
            company=company, field_key=effect.field_key, op=inverse_op,
            before=current, after=after, source=FieldLog.Source.CONTRACT_ROLLBACK,
            contract=contract, round_no=contract.round_no, operator=operator,
        )
        reverted += 1
    return reverted


def _write_base_value(company, field_key, value):
    """写「当前数据」行（无财年行）——补录同步的落点。"""
    row, _created = CompanyFieldValue.objects.get_or_create(
        company=company, field_key=field_key, fiscal_year=None,
        defaults={'value': value, 'version': 1},
    )
    if not _created:
        row.value = value
        row.version += 1
        row.save(update_fields=['value', 'version', 'updated_at'])
    return row


def request_modify(contract: Contract, *, user, reason: str):
    """T6：任意一方申请修改（事务内锁合同行）。"""
    return run_locked(contract, lambda c: _request_modify(c, user=user, reason=reason))


def _request_modify(contract: Contract, *, user, reason: str):
    """T6：任意一方申请修改（须填写申请理由）。"""
    if contract.status != Contract.Status.POSTED:
        raise ContractError(f'当前状态 {contract.status} 不允许申请修改')
    if not (reason or '').strip():
        raise ContractError('申请理由必填')
    # 同一公司同一时间只允许一个合同处于修改流程（否则两份合同互相冻结、谁也无法落账）
    company_ids = {p.get('companyId') for p in contract.parties if p.get('companyId')}
    if company_ids:
        blocker = (
            ContractFreeze.objects
            .filter(company_id__in=company_ids, field_key=ALL_FIELDS, unfrozen_at__isnull=True)
            .exclude(contract=contract)
            .select_related('contract')
            .first()
        )
        if blocker is not None:
            label = blocker.contract.unified_number or blocker.contract.id
            raise ContractError(f'参与方公司有合同正在修改（合同 {label}），暂不能申请修改')
    mod = ContractModRequest.objects.create(
        contract=contract, requested_by=user.id, requested_by_username=user.username,
        reason=reason.strip(), status=ContractModRequest.Status.APPLYING,
    )
    contract.status = Contract.Status.MOD_APPLYING
    contract.save(update_fields=['status', 'updated_at'])
    # 进入修改流程：冻结参与方公司全部资源（修改完成/驳回时解冻）
    freeze_contract(contract)
    from apps.competition.messages.services import notify_competition_super_admins
    notify_competition_super_admins(
        kind='CONTRACT_MOD_APPLYING',
        title=f'合同 {contract.unified_number or contract.id} 申请修改',
        body=f'{user.username} 申请修改合同：{reason.strip()}',
        payload={'contractId': contract.id, 'modRequestId': mod.id},
    )
    return mod


def review_modify(contract: Contract, *, user, approve: bool, note: str = ''):
    """T7/T7'：超级管理员审核修改申请（事务内锁合同行）。"""
    return run_locked(
        contract, lambda c: _review_modify(c, user=user, approve=approve, note=note))


def _review_modify(contract: Contract, *, user, approve: bool, note: str = ''):
    """T7 / T7'：超级管理员审核修改申请。"""
    if contract.status != Contract.Status.MOD_APPLYING:
        raise ContractError(f'当前状态 {contract.status} 不在修改申请中')
    mod = contract.mod_requests.filter(status=ContractModRequest.Status.APPLYING).first()
    if mod is None:
        raise ContractError('没有待审核的修改申请')
    mod.reviewed_by = user.id
    mod.review_note = note or ''
    if approve:
        mod.status = ContractModRequest.Status.EDITING
        mod.save()
        contract.status = Contract.Status.MOD_EDITING
        contract.save(update_fields=['status', 'updated_at'])
        # 修改期间保持冻结：只有本合同自己的修改流程能改字段
    else:
        mod.status = ContractModRequest.Status.REJECTED
        mod.save()
        contract.status = Contract.Status.POSTED
        contract.save(update_fields=['status', 'updated_at'])
        unfreeze_contract(contract, reason='修改申请被驳回，资源解冻')
    _notify_mod_parties(contract, f'修改申请{"已通过" if approve else "已被驳回"}',
                        f'审核人 {user.username}：{note or ("通过" if approve else "驳回")}')
    return mod


def submit_changes(contract: Contract, *, user, inputs=None, parties=None):
    """T9/T10：修改定稿（事务内锁合同行，防重复提交）。"""
    return run_locked(
        contract,
        lambda c: _submit_changes(c, user=user, inputs=inputs, parties=parties))


def _submit_changes(contract: Contract, *, user, inputs=None, parties=None):
    """T9/T10：修改定稿 → 回滚旧落账 → 运行新的检查 → 自动执行 → 根据新的内容修改落账。"""
    if contract.status != Contract.Status.MOD_EDITING:
        raise ContractError(f'当前状态 {contract.status} 不允许提交修改')
    mod = contract.mod_requests.filter(status=ContractModRequest.Status.EDITING).first()
    if mod is None:
        raise ContractError('没有进行中的修改流程')

    # 2026-11 决策：取消「其他方逐一同意」这一环，超级管理员审核通过后即可直接修改并提交。

    # 运行新的检查（§3.3 T9 守卫）
    new_inputs = inputs if inputs is not None else contract.inputs
    new_parties = parties if parties is not None else contract.parties
    module = load_contract_module(contract)
    problems = _validate_inputs(module, new_parties, new_inputs)
    if problems:
        raise ContractError('修改内容校验失败：' + '；'.join(problems))

    old_inputs, old_parties = contract.inputs, contract.parties
    contract.inputs, contract.parties = new_inputs, new_parties
    try:
        check_problems, check_basis = run_check_ex(
            module, contract, basis=_contract_basis(contract))
    finally:
        contract.inputs, contract.parties = old_inputs, old_parties
    record_check(contract, 'MODIFY', check_problems, user=user, basis=check_basis)  # 修改后新检查落库
    if check_problems:
        raise CheckFailedError('新的检查未通过：' + '；'.join(check_problems))

    operator = user
    try:
        with comp_atomic():
            old_round = contract.round_no
            contract.inputs = new_inputs
            contract.parties = new_parties
            contract.status = Contract.Status.PENDING_EXEC
            contract.round_no += 1
            contract.save(update_fields=['inputs', 'parties', 'status', 'round_no', 'updated_at'])
            rollback_round(contract, operator=operator, round_no=old_round)  # 回滚旧落账
            mod.status = ContractModRequest.Status.APPROVED
            mod.save(update_fields=['status', 'updated_at'])
            _execute_after_modify(contract)
    except CheckFailedError as exc:
        # 重落账检查失败 → 整个修改事务回滚（合同维持原落账）；补记失败留痕（新轮次号）
        record_check(contract, 'RECHECK', [str(exc)], user=user,
                     round_no=contract.round_no + 1)
        raise
    return contract


def _execute_after_modify(contract: Contract):
    """修改后重新进入执行流：自动执行 → 再次检查 → 重新落账（round 保持，调用方已开事务）。"""
    _execute(contract, operator=_actor(contract),
             source=FieldLog.Source.CONTRACT_REPOST,
             recheck_error='重落账前检查未通过：')
    # 修改完成：重新落账后解冻，恢复正常手工修改
    unfreeze_contract(contract, reason='修改完成，资源解冻')
    _notify_mod_parties(contract, '修改完成，合同已重新落账',
                        f'统一编号 {contract.unified_number}（第 {contract.round_no} 轮）')


def review_backfill(contract: Contract, *, user, approve: bool, note: str = ''):
    """补录审核（事务内锁合同行）。"""
    return run_locked(
        contract, lambda c: _review_backfill(c, user=user, approve=approve, note=note))


def _review_backfill(contract: Contract, *, user, approve: bool, note: str = ''):
    """补录合同需超级管理员审核：通过 → DRAFT 确认链；驳回 → 取消。"""
    if contract.status != Contract.Status.BACKFILL_REVIEW:
        raise ContractError(f'当前状态 {contract.status} 不在补录审核中')
    if approve:
        contract.status = Contract.Status.DRAFT
    else:
        contract.status = Contract.Status.CANCELLED
    contract.save(update_fields=['status', 'updated_at'])
    from apps.competition.messages.services import send_message
    send_message(
        contract.created_by, kind='CONTRACT_BACKFILL_REVIEW',
        title=f'补录合同 {contract.name or contract.id} 审核{"通过" if approve else "被驳回"}',
        body=f'审核人 {user.username}：{note or ("通过" if approve else "驳回")}',
        payload={'contractId': contract.id},
    )
    return contract


def _notify_pending_party(contract: Contract):
    from apps.competition.messages.services import send_message
    parties = sorted(contract.parties, key=lambda p: p.get('confirmOrder', 0))
    index = contract.pending_party_index
    if index >= len(parties):
        return
    current = parties[index]
    from apps.common.authority import company_actor_ids
    for uid in company_actor_ids(current.get('companyId')):
        send_message(
            uid, kind='CONTRACT_CONFIRM_PENDING',
            title=f'合同 {contract.name or contract.unified_number or contract.id} 等待你确认',
            body=f'参与方 {current["role"]} 请确认合同。',
            payload={'contractId': contract.id, 'partyRole': current['role']},
        )


def _notify_mod_parties(contract: Contract, title: str, body: str):
    from apps.competition.messages.services import send_message
    from apps.common.authority import company_actor_ids
    users = set()
    for p in contract.parties:
        users |= company_actor_ids(p.get('companyId'))
    users.add(contract.created_by)
    for uid in users:
        send_message(uid, kind='CONTRACT_MOD', title=title, body=body,
                     payload={'contractId': contract.id})
