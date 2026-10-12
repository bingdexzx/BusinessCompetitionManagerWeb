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

from apps.competition.contracts.engine import _effect_after
from apps.competition.contracts.models import Contract, ContractFieldEffect


def _chain_rows(company_id, field_key):
    """某 (公司, 字段) 的生效效果链（按编号顺序；已回滚轮次排除）。"""
    rows = (
        ContractFieldEffect.objects
        .filter(company_id=company_id, field_key=field_key)
        .select_related('contract')
        .order_by('contract__numbered_at', 'contract_id', 'created_at', 'id')
    )
    return [e for e in rows if e.round_no == e.contract.round_no]


def field_chain(company_id, field_key) -> dict:
    """单字段账本链：initialValue → 各合同节点（当时值 + 重演值）→ currentValue。"""
    chain = _chain_rows(company_id, field_key)
    if not chain:
        return {
            'companyId': company_id, 'fieldKey': field_key,
            'initialValue': None, 'currentValue': None, 'nodes': [],
        }
    initial = chain[0].before_raw
    cur = initial
    nodes = []
    for e in chain:
        before = cur
        after = _effect_after(before, e.op, e.value_raw)
        contract = e.contract
        nodes.append({
            'effectId': e.id,
            'contractId': contract.id,
            'contractName': contract.name or f'合同 #{contract.id}',
            'unifiedNumber': contract.unified_number,
            'roundNo': e.round_no,
            'op': e.op,
            'value': e.value_raw,
            'auditBefore': e.before_raw,      # 落账当时值（不可变审计）
            'auditAfter': e.after_raw,
            'replayBefore': before,            # 重演值（按当前内容重算，自动同步）
            'replayAfter': after,
        })
        cur = after
    return {
        'companyId': company_id, 'fieldKey': field_key,
        'initialValue': initial, 'currentValue': cur, 'nodes': nodes,
    }


def _active_effects(contract: Contract):
    return list(contract.effects.filter(round_no=contract.round_no)
                .order_by('created_at', 'id'))


def annotate_effects(contract: Contract) -> list:
    """合同效果 + 重演前后值（replayBefore/replayAfter）；已回滚轮次不参与。"""
    pairs = {(e.company_id, e.field_key) for e in _active_effects(contract)}
    chains = {pair: field_chain(*pair) for pair in pairs}
    out = []
    for e in contract.effects.order_by('-round_no', 'created_at', 'id'):
        active = e.round_no == contract.round_no
        node = None
        if active:
            for n in chains[(e.company_id, e.field_key)]['nodes']:
                if n['effectId'] == e.id:
                    node = n
                    break
        out.append({
            'id': e.id, 'companyId': e.company_id, 'fieldKey': e.field_key,
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
    """检查记录 + 依据重演替换（replayBasis：链上对应节点的重算值）。"""
    from apps.competition.contracts.models import ContractCheck

    party_companies = {p['role']: p.get('companyId') for p in (contract.parties or [])}
    out = []
    for check in contract.checks.all():
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
                    key = (company_id, field)
                    chain = chains.get(key) if chains else field_chain(*key)
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
    """合同资金账本链：该合同触及的每个 (公司, 字段) 的全链（含检查依据重演）。"""
    pairs = {(e.company_id, e.field_key) for e in _active_effects(contract)}
    chains = {pair: field_chain(*pair) for pair in pairs}
    return {
        'chains': [chains[pair] for pair in sorted(pairs)],
        'checks': annotate_checks(contract, chains),
    }
