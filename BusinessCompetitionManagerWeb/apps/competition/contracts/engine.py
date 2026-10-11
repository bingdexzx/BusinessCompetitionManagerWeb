"""合同引擎（§3 合同状态机、§7 合同引擎与落账设计、§14.2 字段日志）。

状态流转（转移表 §3.3）：
  T1 create        → DRAFT            参与方与输入满足 inputSchema
  T2 submit        → PENDING_PARTY    运行 check()（保证创建即能执行）
  T3 confirm       → PENDING_PARTY/PENDING_EXEC   N 方按参与方顺序依次确认
  T4 numbering     → EXECUTED         确认链完成 → 系统生成统一编号 → **自动执行**
  T5 recheck       → POSTED           **再次运行检查**通过 → 落账 + 冻结
  T6 request_modify→ MOD_APPLYING     任意一方申请修改（理由）
  T7 approve       → MOD_EDITING      超管通过（解冻，仅申请方可改）
  T7' reject       → POSTED           超管驳回
  T8 other approve → MOD_EDITING      所有其他方逐一通过（缺一不可）
  T8' other reject → POSTED           任一其他方驳回
  T9 submit_changes→ PENDING_EXEC     回滚旧落账 → 运行新的检查 → 重新执行
  T10              → EXECUTED → POSTED（round_no+1，根据新的内容修改落账）

补录合同（is_backfill，决策 D14）：BACKFILL_REVIEW（超管审核）→ DRAFT 确认链；
以**所补录财年末备份快照**为执行基准；落账后**非财年定时器字段自动同步**（BACKFILL_SYNC）。

执行 = 落账前的字段改写（apply 产生效果）、检查保证正确（check）、落账冻结生效（§3.4）。
回滚 = 逆序重放（ADD↔SUB、SET 恢复 beforeRaw，§7.2）。
"""

from django.db import transaction
from django.utils import timezone

from apps.common import context as ctx
from apps.competition.contracts.models import (
    Contract, ContractConfirmation, ContractFieldEffect, ContractModRequest, NumberSequence,
)
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.competition.ledger.models import ContractFreeze


class ContractError(Exception):
    """业务错误（前置守卫不满足 / 检查不通过）。"""


def comp_atomic():
    """比赛库事务（多库架构下事务必须落在比赛库连接上，§5.2）。"""
    return transaction.atomic(using=(ctx.get_competition_alias() or 'default'))


# ================================================================ 插件与上下文


def load_contract_module(contract: Contract):
    """按合同锁定的插件版本加载合同类型插件（§5.4 版本化）。"""
    from apps.competition.contracts.services import contract_module_for
    return contract_module_for(contract.contract_type_key, contract.plugin_version)


def party_company_map(contract: Contract) -> dict:
    from apps.competition.companies.models import Company
    out = {}
    for p in contract.parties:
        company = Company.objects.filter(pk=p.get('companyId')).first()
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


def _basis_value(company, field_key, basis):
    """补录合同执行基准（所补录财年末备份快照，§3.4）。"""
    if basis is None:
        return _read_value(company, field_key, None)
    snap = basis.get(company.id) or {}
    return snap.get(field_key, 0)


def build_context(contract: Contract, *, basis=None):
    """构造插件 ctx（§8.1：参与方解析、输入参数、公司字段读取，不暴露 ORM）。"""
    from plugins_runtime.api import ContractContext

    companies = party_company_map(contract)
    fiscal_year = contract.fiscal_year

    fields = {}
    for role, company in companies.items():
        keys = set(IndustryField.objects.values_list('field_key', flat=True))
        keys |= set(CompanyFieldValue.objects.filter(company=company)
                    .values_list('field_key', flat=True))
        for key in keys:
            if basis is not None:
                fields[(role, key)] = _basis_value(company, key, basis)
            else:
                fields[(role, key)] = _read_value(company, key, fiscal_year)

    return ContractContext(
        parties={role: company.name for role, company in companies.items()},
        inputs=contract.inputs or {},
        fields=fields,
    )


def run_check(module, contract: Contract, *, basis=None) -> list:
    """运行插件 check(ctx)（§7.3 四个检查点共用）。返回问题列表。"""
    problems = module.check(build_context(contract, basis=basis))
    return [str(p) for p in (problems or [])]


def run_apply(module, contract: Contract, *, basis=None) -> list:
    """运行插件 apply(ctx) 得到效果列表（§7.2）。"""
    effects = module.apply(build_context(contract, basis=basis)) or []
    return list(effects)


# ================================================================ 效果与落账


def _resolve_effect_company(effect, companies: dict):
    """Effect.company 可以是参与方角色或公司名（§7.2）。"""
    if effect.company in companies:
        return companies[effect.company]
    for company in companies.values():
        if company.name == effect.company:
            return company
    raise ContractError(f'效果指向未知公司/角色：{effect.company}')


def _effect_after(before, op, value):
    def _num(v):
        return float(v) if isinstance(v, (int, float)) else 0.0

    if op == 'ADD':
        return _num(before) + _num(value)
    if op == 'SUB':
        return _num(before) - _num(value)
    return value


def _write_value(company, field_key, value, fiscal_year):
    """写字段值（财务报表按财年行，实体信息表按无财年行），乐观锁 version+1。

    fiscal_year=None 时：财务报表写最新财年行（无则无财年行），实体信息表写无财年行。
    """
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


def _write_field_log(*, company, field_key, op, before, after, source, contract,
                     round_no, operator, event=FieldLog.Event.VALUE_CHANGE):
    definition = IndustryField.objects.filter(field_key=field_key).first()
    snapshot = ctx.get_device_snapshot() or {}
    return FieldLog.objects.create(
        company=company,
        field_key=field_key,
        data_table=definition.data_table if definition else '',
        event=event,
        op=op,
        before_raw=before,
        after_raw=after,
        source=source,
        contract=contract,
        round_no=round_no,
        operator_id=getattr(operator, 'id', None),
        operator_username=getattr(operator, 'username', ''),
        device_snapshot=snapshot,
        ip=snapshot.get('ip'),
        trace_id=ctx.get_trace_id() or '',
    )


def apply_effects(contract: Contract, effects, *, source, operator, basis=None):
    """落账引擎（§7.2）：单事务内读当前值 → 计算后值 → 写字段值 + 不可变审计 + 字段日志。"""
    companies = party_company_map(contract)
    fiscal_year = contract.fiscal_year
    for effect in effects:
        company = _resolve_effect_company(effect, companies)
        if basis is not None:
            before = _basis_value(company, effect.field, basis)
        else:
            before = _read_value(company, effect.field, fiscal_year)
        after = _effect_after(before, effect.op, effect.value)
        _write_value(company, effect.field, after, fiscal_year)
        ContractFieldEffect.objects.create(
            contract=contract, company=company, field_key=effect.field,
            op=effect.op, value_raw=effect.value,
            before_raw=before, after_raw=after, round_no=contract.round_no,
        )
        _write_field_log(
            company=company, field_key=effect.field, op=effect.op,
            before=before, after=after, source=source, contract=contract,
            round_no=contract.round_no, operator=operator,
        )


def rollback_round(contract: Contract, *, operator, round_no=None):
    """回滚旧落账 = 按效果审计逆序重放（§3.4 修改 = 回滚 + 重做）。"""
    companies = party_company_map(contract)
    fiscal_year = contract.fiscal_year
    target_round = contract.round_no if round_no is None else round_no
    effects = list(contract.effects.filter(round_no=target_round).order_by('-created_at', '-id'))
    for effect in effects:
        from apps.competition.companies.models import Company
        company = Company.objects.filter(pk=effect.company_id).first()
        if company is None:
            continue
        before = _read_value(company, effect.field_key, fiscal_year)
        if effect.op == 'ADD':
            after = _effect_after(before, 'SUB', effect.value_raw)
            inverse_op = 'SUB'
        elif effect.op == 'SUB':
            after = _effect_after(before, 'ADD', effect.value_raw)
            inverse_op = 'ADD'
        else:  # SET 恢复 beforeRaw
            after = effect.before_raw
            inverse_op = 'SET'
        _write_value(company, effect.field_key, after, fiscal_year)
        _write_field_log(
            company=company, field_key=effect.field_key, op=inverse_op,
            before=before, after=after, source=FieldLog.Source.CONTRACT_ROLLBACK,
            contract=contract, round_no=contract.round_no, operator=operator,
        )


# ================================================================ 编号（D13）


def generate_unified_number(contract: Contract, competition) -> str:
    """统一编号：类别前缀-比赛代码-财年-流水号（如 PO-2025-FY1-0001）。"""
    from apps.competition.contracts.services import contract_number_prefix

    prefix = contract_number_prefix(contract.contract_type_key) or contract.contract_type_key[:2].upper()
    comp_code = competition.code or str(competition.id)
    fy_part = f'FY{contract.fiscal_year.year}' if contract.fiscal_year_id else 'FY0'
    seq_key = f'{prefix}-{comp_code}-{fy_part}'
    with comp_atomic():
        seq, _ = NumberSequence.objects.select_for_update().get_or_create(
            key=seq_key, defaults={'last_value': 0})
        seq.last_value += 1
        seq.save(update_fields=['last_value'])
    return f'{prefix}-{comp_code}-{fy_part}-{seq.last_value:04d}'


# ================================================================ 冻结（§7.4，决策 D10）


def freeze_contract(contract: Contract):
    """落账后冻结合同相关资源（字段级）。"""
    seen = set()
    for effect in contract.effects.filter(round_no=contract.round_no):
        key = (effect.company_id, effect.field_key)
        if key in seen:
            continue
        seen.add(key)
        ContractFreeze.objects.get_or_create(
            contract=contract, company_id=effect.company_id, field_key=effect.field_key,
            defaults={'reason': f'合同 {contract.unified_number or contract.id} 落账冻结'},
        )


def unfreeze_contract(contract: Contract, reason: str = ''):
    now = timezone.now()
    contract.freezes.filter(unfrozen_at__isnull=True).update(unfrozen_at=now, reason=reason[:200])


def assert_field_writable(company_id, field_key):
    """手工/非合同写入路径守卫：被冻结字段禁止修改（§7.4）。"""
    frozen = ContractFreeze.objects.filter(
        company_id=company_id, field_key=field_key, unfrozen_at__isnull=True).exists()
    if frozen:
        raise ContractError(f'字段 {field_key} 已被合同落账冻结，禁止其他途径修改')


# ================================================================ 状态机操作


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
        if value in (None, '') and (s.get('required') or s.get('min') is not None):
            problems.append(f'缺少输入项 {s.get("label") or s["key"]}')
        if s.get('min') is not None:
            try:
                if float(value) < float(s['min']):
                    problems.append(f'{s.get("label") or s["key"]} 小于最小值 {s["min"]}')
            except (TypeError, ValueError):
                pass
    return problems


def submit_contract(contract: Contract, *, user):
    """T2：提交草稿，运行 check()（保证创建即能执行）。"""
    if contract.status != Contract.Status.DRAFT:
        raise ContractError(f'当前状态 {contract.status} 不允许提交')
    module = load_contract_module(contract)
    problems = run_check(module, contract)
    if problems:
        raise ContractError('检查未通过：' + '；'.join(problems))
    contract.status = Contract.Status.PENDING_PARTY
    contract.pending_party_index = 0
    contract.save(update_fields=['status', 'pending_party_index', 'updated_at'])
    _notify_pending_party(contract)
    return contract


def confirm_party(contract: Contract, *, user, party_role=None):
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

    # 确认链完成：系统自动生成统一编号 → 立即自动执行（T4）
    contract.status = Contract.Status.PENDING_EXEC
    contract.save(update_fields=['parties', 'pending_party_index', 'status', 'updated_at'])
    _auto_number_and_execute(contract)
    return contract


def _auto_number_and_execute(contract: Contract):
    """编号补完后自动执行（T4/T5/T10）：编号 → 执行 → 再次检查 → 落账 + 冻结。"""
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


def execute_and_post(contract: Contract):
    """PENDING_EXEC → EXECUTED（apply）→ 再次检查 → POSTED（落账 + 冻结）。

    整体一个事务：自动执行失败不落半账（§7.5）。
    """
    module = load_contract_module(contract)
    competition = _competition()
    source = FieldLog.Source.CONTRACT_REPOST if contract.round_no else FieldLog.Source.CONTRACT_POST
    operator = _actor(contract)

    with comp_atomic():
        basis = None
        if contract.is_backfill and contract.fiscal_year_id:
            basis = _backup_basis(contract)

        # 待执行 → 已执行：apply() 产生效果
        effects = run_apply(module, contract, basis=basis)
        contract.status = Contract.Status.EXECUTED
        contract.executed_at = timezone.now()
        contract.save(update_fields=['status', 'executed_at', 'updated_at'])

        # 已执行 → 落账：再次运行检查（获取公司数据并执行检查）
        problems = run_check(module, contract, basis=basis)
        if problems:
            raise ContractError('落账前再次检查未通过：' + '；'.join(problems))

        apply_effects(contract, effects, source=source, operator=operator, basis=basis)
        if contract.is_backfill:
            _backfill_sync(contract, effects, operator)

        contract.status = Contract.Status.POSTED
        contract.posted_at = timezone.now()
        contract.save(update_fields=['status', 'posted_at', 'updated_at'])
        freeze_contract(contract)
    return contract


def _actor(contract: Contract):
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(pk=contract.created_by).first()


def _backup_basis(contract: Contract):
    """补录执行基准：所补录财年末数据表备份快照（§3.4 / §10.2）。"""
    from apps.competition.fiscal.models import FiscalYearBackup
    basis = {}
    for backup in FiscalYearBackup.objects.filter(fiscal_year_id=contract.fiscal_year_id):
        basis[backup.company_id] = backup.snapshot or {}
    return basis


def _backfill_sync(contract: Contract, effects, operator):
    """补录合同落账后：**非财年定时器字段自动同步修改信息**（§2.2 阶段五）。

    - 实体信息表字段的效果已直接写入当前值（见 _write_value）；
    - 财务报表字段（非定时器）把变化同步到当前数据（无财年行，BACKFILL_SYNC）；
    - 财年定时器字段只改写所补录财年的数据行，不向后同步。
    """
    companies = party_company_map(contract)
    timer_keys = set(IndustryField.objects.filter(timer_enabled=True)
                     .values_list('field_key', flat=True))
    for effect in effects:
        if effect.field in timer_keys:
            continue
        definition = IndustryField.objects.filter(field_key=effect.field).first()
        if not definition or definition.data_table != IndustryField.DataTable.FINANCE:
            continue
        company = _resolve_effect_company(effect, companies)
        current = _read_value(company, effect.field, None)
        after = _effect_after(current, effect.op, effect.value)
        _write_base_value(company, effect.field, after)
        _write_field_log(
            company=company, field_key=effect.field, op=effect.op,
            before=current, after=after, source=FieldLog.Source.BACKFILL_SYNC,
            contract=contract, round_no=contract.round_no, operator=operator,
        )


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


# ================================================================ 修改流程（T6–T10）


def request_modify(contract: Contract, *, user, reason: str):
    """T6：任意一方申请修改（须填写申请理由）。"""
    if contract.status != Contract.Status.POSTED:
        raise ContractError(f'当前状态 {contract.status} 不允许申请修改')
    if not (reason or '').strip():
        raise ContractError('申请理由必填')
    mod = ContractModRequest.objects.create(
        contract=contract, requested_by=user.id, requested_by_username=user.username,
        reason=reason.strip(), status=ContractModRequest.Status.APPLYING,
    )
    contract.status = Contract.Status.MOD_APPLYING
    contract.save(update_fields=['status', 'updated_at'])
    from apps.competition.messages.services import notify_competition_super_admins
    notify_competition_super_admins(
        kind='CONTRACT_MOD_APPLYING',
        title=f'合同 {contract.unified_number or contract.id} 申请修改',
        body=f'{user.username} 申请修改合同：{reason.strip()}',
        payload={'contractId': contract.id, 'modRequestId': mod.id},
    )
    return mod


def review_modify(contract: Contract, *, user, approve: bool, note: str = ''):
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
        unfreeze_contract(contract, reason='修改申请通过，解冻待重落账')
    else:
        mod.status = ContractModRequest.Status.REJECTED
        mod.save()
        contract.status = Contract.Status.POSTED
        contract.save(update_fields=['status', 'updated_at'])
        freeze_contract(contract)
    _notify_mod_parties(contract, f'修改申请{"已通过" if approve else "已被驳回"}',
                        f'审核人 {user.username}：{note or ("通过" if approve else "驳回")}')
    return mod


def other_party_review(contract: Contract, *, user, approve: bool, note: str = ''):
    """T8 / T8'：所有其他方逐一通过（任一方驳回 → 回到落账态）。"""
    if contract.status != Contract.Status.MOD_EDITING:
        raise ContractError(f'当前状态 {contract.status} 不在修改中')
    mod = contract.mod_requests.filter(status=ContractModRequest.Status.EDITING).first()
    if mod is None:
        raise ContractError('没有进行中的修改流程')
    if user.id == mod.requested_by:
        raise ContractError('申请方不能代替其他方表态')

    approvals = list(mod.other_party_approvals or [])
    if any(a.get('userId') == user.id for a in approvals):
        raise ContractError('你已表态过')
    approvals.append({
        'userId': user.id, 'username': user.username,
        'approved': bool(approve), 'note': note or '',
        'at': timezone.now().isoformat(),
    })
    mod.other_party_approvals = approvals
    mod.save(update_fields=['other_party_approvals', 'updated_at'])

    if not approve:
        # 任一其他方驳回 → POSTED（T8'），合同保持原落账
        mod.status = ContractModRequest.Status.REJECTED
        mod.review_note = f'{user.username} 驳回：{note or ""}'
        mod.save()
        contract.status = Contract.Status.POSTED
        contract.save(update_fields=['status', 'updated_at'])
        freeze_contract(contract)
        _notify_mod_parties(contract, '修改流程已被其他方驳回',
                            f'{user.username}：{note or "驳回"}')
    return mod


def submit_changes(contract: Contract, *, user, inputs=None, parties=None):
    """T9/T10：修改定稿 → 回滚旧落账 → 运行新的检查 → 自动执行 → 根据新的内容修改落账。"""
    if contract.status != Contract.Status.MOD_EDITING:
        raise ContractError(f'当前状态 {contract.status} 不允许提交修改')
    mod = contract.mod_requests.filter(status=ContractModRequest.Status.EDITING).first()
    if mod is None:
        raise ContractError('没有进行中的修改流程')

    # 所有其他方逐一通过后方可提交（决策 D8）：申请方所在参与方之外的每一方都要通过
    member_ids = _company_member_ids(contract)
    applicant_roles = {
        role for role, uids in member_ids.items() if mod.requested_by in uids
    }
    approved = {a.get('userId') for a in (mod.other_party_approvals or []) if a.get('approved')}
    pending = [
        role for role, uids in member_ids.items()
        if role not in applicant_roles and not (uids & approved)
    ]
    if pending:
        raise ContractError('以下参与方尚未通过修改：' + '、'.join(pending))

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
        check_problems = run_check(module, contract)
    finally:
        contract.inputs, contract.parties = old_inputs, old_parties
    if check_problems:
        raise ContractError('新的检查未通过：' + '；'.join(check_problems))

    operator = user
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
    return contract


def _execute_after_modify(contract: Contract):
    """修改后重新进入执行流：自动执行 → 再次检查 → 重新落账（round 保持）。"""
    module = load_contract_module(contract)
    competition = _competition()
    operator = _actor(contract)
    basis = _backup_basis(contract) if contract.is_backfill else None

    effects = run_apply(module, contract, basis=basis)
    contract.status = Contract.Status.EXECUTED
    contract.executed_at = timezone.now()
    contract.save(update_fields=['status', 'executed_at', 'updated_at'])

    problems = run_check(module, contract, basis=basis)
    if problems:
        raise ContractError('重落账前检查未通过：' + '；'.join(problems))

    apply_effects(contract, effects, source=FieldLog.Source.CONTRACT_REPOST,
                  operator=operator, basis=basis)
    contract.status = Contract.Status.POSTED
    contract.posted_at = timezone.now()
    contract.save(update_fields=['status', 'posted_at', 'updated_at'])
    freeze_contract(contract)
    _notify_mod_parties(contract, '修改完成，合同已重新落账',
                        f'统一编号 {contract.unified_number}（第 {contract.round_no} 轮）')


def _company_member_ids(contract: Contract) -> dict:
    """参与方公司 → 可表态的用户 ID 集（队长/队员、所辖管理员、比赛超管）。"""
    from apps.common.authority import company_actor_ids
    return {p['role']: company_actor_ids(p.get('companyId')) for p in contract.parties}


# ================================================================ 补录审核（§3.4）


def review_backfill(contract: Contract, *, user, approve: bool, note: str = ''):
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


# ================================================================ 通知


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
