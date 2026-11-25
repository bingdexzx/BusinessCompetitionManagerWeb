"""账本重演（查账同步）——需求方口径确认（2026-10）：

- **不可变审计**（ContractFieldEffect.before/after）＝ 落账当时的事实，永不改写；
- **重演值**（replay）＝ 按合同**编号顺序**（=执行链）从链起点重放**当前生效轮次**的效果：
  上游合同修改重落后，下游节点的重演值**自动重算**——
  例：合同一 1000→800、合同二 800→600；合同一改为 -100 后，链条重演为
  合同一 1000→900、**合同二 900→700**（当时值 800→600 保留为审计）；
- **检查依据**（ContractCheck.basis 当时快照）展示时按链上重算值替换（replayBasis）。

链顺序按 `contract.numbered_at`（编号即执行序；修改后的合同保持原链位，
符合查账心智）。参与链的效果 = `round_no == contract.round_no`（已回滚轮次自动排除）。
"""

from apps.competition.contracts.models import Contract, ContractFieldEffect
from plugins_runtime import ops


def _chain_rows(company_id, field_key):
    """某 (公司, 字段) 的生效效果链（按编号顺序；已回滚轮次、已删除合同排除）。"""
    rows = (
        ContractFieldEffect.objects
        .filter(company_id=company_id, field_key=field_key,
                contract__deleted_at__isnull=True)
        .select_related('contract')
        .order_by('contract__numbered_at', 'contract_id', 'created_at', 'id')
    )
    return [e for e in rows if e.round_no == e.contract.round_no]


def _real_value(company_id, field_key):
    """字段当前的真实值（实体行优先，其次最新财年行）。"""
    from apps.competition.industries.models import CompanyFieldValue

    try:
        row = CompanyFieldValue.objects.filter(
            company_id=company_id, field_key=field_key, fiscal_year__isnull=True).first()
        if row is None:
            row = (CompanyFieldValue.objects
                   .filter(company_id=company_id, field_key=field_key,
                           fiscal_year__isnull=False)
                   .order_by('-fiscal_year__year').first())
    except RuntimeError:
        # 无比赛上下文（纯函数/重演单测）：拿不到真实值就返回 None
        return None
    return row.value if row is not None else None


def _non_contract_changes(company_id, field_key, limit=20):
    """不入合同链的字段变更（手工修改 / 财年定时器 / 公式重算 / 补录同步 / 股票）。"""
    from apps.competition.fieldlogs.models import FieldLog

    try:
        rows = (FieldLog.objects
                .filter(company_id=company_id, field_key=field_key, contract__isnull=True,
                        event=FieldLog.Event.VALUE_CHANGE)
                .order_by('-occurred_at')[:limit])
        rows = list(rows)
    except RuntimeError:
        # 无比赛上下文（纯函数/重演单测）：没有非合同变更可列
        return []
    return [
        {
            'id': row.id,
            'source': row.source,
            'sourceLabel': row.get_source_display(),
            'op': row.op,
            'before': row.before_raw,
            'after': row.after_raw,
            'operator': row.operator_username or '系统',
            'occurredAt': row.occurred_at.isoformat(),
        }
        for row in rows
    ]


def _assemble_chain(company_id, field_key, rows, real_value, changes) -> dict:
    """由已取好的效果行/真实值/非合同变更装配一条链（纯内存，无 SQL）。"""
    if not rows:
        return {
            'companyId': company_id, 'fieldKey': field_key,
            'initialValue': None, 'currentValue': real_value,
            'replayValue': real_value, 'drift': 0, 'nodes': [],
            'nonContractChanges': changes,
        }
    initial = rows[0].before_raw
    cur = initial
    nodes = []
    for effect in rows:
        before = cur
        after = ops.apply(before, effect.op, effect.value_raw)
        contract = effect.contract
        nodes.append({
            'effectId': effect.id,
            'contractId': contract.id,
            'contractName': contract.name or f'合同 #{contract.id}',
            'unifiedNumber': contract.unified_number,
            'roundNo': effect.round_no,
            'op': effect.op,
            'value': effect.value_raw,
            'auditBefore': effect.before_raw,
            'auditAfter': effect.after_raw,
            'replayBefore': before,
            'replayAfter': after,
        })
        cur = after
    try:
        drift = float(real_value) - float(cur) if real_value is not None else None
    except (TypeError, ValueError):
        drift = None
    return {
        'companyId': company_id, 'fieldKey': field_key,
        'initialValue': initial,
        'currentValue': real_value,
        'replayValue': cur,
        'drift': drift,
        'nodes': nodes,
        'nonContractChanges': changes,
    }


def _serialize_change(row) -> dict:
    return {
        'id': row.id,
        'source': row.source,
        'sourceLabel': row.get_source_display(),
        'op': row.op,
        'before': row.before_raw,
        'after': row.after_raw,
        'operator': row.operator_username or '系统',
        'occurredAt': row.occurred_at.isoformat(),
    }


def field_chains(pairs) -> dict:
    """批量建链：一次取效果、一次取真实值、一次取非合同变更，供详情/账本使用。

    ``pairs`` = {(company_id, field_key)}；返回同 key 的链字典。
    200+ 轮修改的合同详情曾因逐链查询放大到上千条 SQL，这里是主要修复点。
    """
    pairs = {(int(c), str(f)) for c, f in pairs if c and f}
    if not pairs:
        return {}
    from apps.competition.fieldlogs.models import FieldLog
    from apps.competition.industries.models import CompanyFieldValue

    company_ids = {c for c, _f in pairs}
    field_keys = {f for _c, f in pairs}

    # 1) 生效效果链：一条 SQL 取全部
    rows = (ContractFieldEffect.objects
            .filter(contract__deleted_at__isnull=True,
                    company_id__in=company_ids, field_key__in=field_keys)
            .select_related('contract')
            .order_by('contract__numbered_at', 'contract_id', 'created_at', 'id'))
    grouped = {}
    for effect in rows:
        if effect.round_no != effect.contract.round_no:
            continue   # 已回滚轮次不进链
        grouped.setdefault((effect.company_id, effect.field_key), []).append(effect)

    # 2) 真实值：实体行优先，其次最新财年
    real = {}
    for row in (CompanyFieldValue.objects
                .filter(company_id__in=company_ids, field_key__in=field_keys)
                .order_by('field_key', 'company_id')):
        key = (row.company_id, row.field_key)
        current = real.get(key)
        if current is None:
            real[key] = row
        elif current.fiscal_year_id is not None and (
                row.fiscal_year_id is None
                or (row.fiscal_year.year or 0) > (current.fiscal_year.year or 0)):
            real[key] = row

    def real_value(key):
        row = real.get(key)
        return None if row is None else row.value

    # 3) 非合同变更：一次取最近若干条，按 pair 分组截 20 条
    limit = max(200, 20 * len(pairs))
    changes = {}
    logs = (FieldLog.objects
            .filter(company_id__in=company_ids, field_key__in=field_keys,
                    contract__isnull=True, event=FieldLog.Event.VALUE_CHANGE)
            .order_by('-occurred_at')[:limit])
    for log in logs:
        bucket = changes.setdefault((log.company_id, log.field_key), [])
        if len(bucket) < 20:
            bucket.append(_serialize_change(log))

    return {
        key: _assemble_chain(key[0], key[1], grouped.get(key, []),
                             real_value(key), changes.get(key, []))
        for key in pairs
    }


def field_chain(company_id, field_key) -> dict:
    """单条链（内部走批量实现，保持旧接口）。"""
    return field_chains({(company_id, field_key)})[(int(company_id), str(field_key))]


def _active_effects(contract: Contract):
    return list(contract.effects.filter(round_no=contract.round_no)
                .order_by('created_at', 'id'))


def annotate_effects(contract: Contract) -> list:
    """合同效果 + 重演前后值（replayBefore/replayAfter）；已回滚轮次不参与。

    区域字段效果（``region_id`` 非空）不参与公司字段链重演（链是按公司字段建的），
    只回显审计前后值；``target`` 区分 COMPANY / REGION。
    """
    pairs = {(e.company_id, e.field_key) for e in _active_effects(contract) if not e.region_id}
    chains = field_chains(pairs)
    out = []
    for e in contract.effects.select_related('region').order_by('-round_no', 'created_at', 'id'):
        active = e.round_no == contract.round_no
        node = None
        if active and not e.region_id:
            for n in chains[(e.company_id, e.field_key)]['nodes']:
                if n['effectId'] == e.id:
                    node = n
                    break
        out.append({
            'id': e.id, 'companyId': e.company_id, 'fieldKey': e.field_key,
            'target': 'REGION' if e.region_id else 'COMPANY',
            'regionId': e.region_id,
            'regionName': e.region.name if e.region_id else '',
            'op': e.op, 'value': e.value_raw,
            'before': e.before_raw, 'after': e.after_raw,
            'roundNo': e.round_no, 'createdAt': e.created_at.isoformat(),
            'roundStatus': 'ACTIVE' if active else 'ROLLED_BACK',
            'isCurrent': active,
            'replayBefore': node['replayBefore'] if node else None,
            'replayAfter': node['replayAfter'] if node else None,
        })
    return out


def annotate_checks(contract: Contract, chains: dict = None) -> list:
    """检查记录 + 依据重演替换（replayBasis：链上对应节点的重算值）。

    性能：``chains`` 为空时先一次性把「检查依据涉及的 (公司, 字段)」全算成链，
    避免每个检查项 × 每个字段都单独 ``field_chain``（200+ 轮合同会放大到上千条 SQL）。
    """
    party_companies = {p['role']: p.get('companyId') for p in (contract.parties or [])}
    checks = list(contract.checks.all())
    if chains is None:
        pairs = set()
        for check in checks:
            for role, fields in (check.basis or {}).items():
                company_id = party_companies.get(role)
                if not company_id:
                    continue
                for field in (fields or {}):
                    pairs.add((int(company_id), field))
        chains = field_chains(pairs)

    out = []
    for check in checks:
        # 本地序列化（不依赖 views，避免循环依赖）
        row = {
            'id': check.id,
            'roundNo': check.round_no,
            'checkpoint': check.checkpoint,
            'checkpointLabel': check.get_checkpoint_display(),
            'problems': check.problems,
            'passed': check.passed,
            'checkedBy': check.checked_by_username or (str(check.checked_by) if check.checked_by else '系统'),
            'checkedAt': check.checked_at.isoformat(),
            'roundStatus': 'ACTIVE' if check.round_no == contract.round_no else 'HISTORY',
            'basis': check.basis or {},
        }
        replay_basis = {}
        for role, fields in (check.basis or {}).items():
            company_id = party_companies.get(role)
            for field, value in (fields or {}).items():
                replay_value = value
                if company_id:
                    chain = chains.get((int(company_id), field))
                    if chain:
                        # 该合同在链上的节点位置 → 重演前值（=检查时「应看到」的重算值）
                        for n in chain['nodes']:
                            if n['contractId'] == contract.id:
                                replay_value = n['replayBefore']
                                break
                replay_basis.setdefault(role, {})[field] = replay_value
        row['replayBasis'] = replay_basis
        out.append(row)
    return out


def contract_ledger(contract: Contract) -> dict:
    """合同资金账本链：该合同触及的每个 (公司, 字段) 的全链（含检查依据重演）。

    区域字段效果不属于公司资金链，不在此展开（在效果审计里展示）。
    """
    pairs = {(e.company_id, e.field_key) for e in _active_effects(contract) if not e.region_id}
    chains = field_chains(pairs)
    return {
        'chains': [chains[pair] for pair in sorted(pairs)],
        'checks': annotate_checks(contract, chains),
    }
