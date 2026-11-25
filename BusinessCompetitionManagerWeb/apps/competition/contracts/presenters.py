"""合同展示组装（序列化 / 确认时间线 / 检查依据），从 views 拆出。

视图只做鉴权与状态机调用；纯展示组装（含审计可见范围过滤）集中在本模块。
"""

from django.conf import settings

from django.utils import timezone

from apps.common import context as ctx
from apps.common.authority import audit_company_ids
from apps.common.labels import op_label
from apps.competition.contracts.models import Contract
from apps.competition.fieldlogs.models import FieldLog


def _company_map_for(contracts) -> dict:
    """批量解析合同涉及的公司（消 N+1：2000 合同列表原先每行每方各查一次公司）。"""
    from apps.competition.companies.models import Company

    ids = set()
    for c in contracts:
        for p in (c.parties or []):
            if p.get('companyId'):
                ids.add(p['companyId'])
    if not ids:
        return {}
    return {co.id: co for co in Company.objects.filter(pk__in=ids)}


def _party_data(contract: Contract, company_map=None) -> list:
    from apps.competition.companies.models import Company
    out = []
    for p in sorted(contract.parties, key=lambda x: x.get('confirmOrder', 0)):
        company = (company_map or {}).get(p.get('companyId'))
        if company is None and company_map is None:
            company = Company.objects.filter(pk=p.get('companyId')).first()
        out.append({
            'role': p['role'],
            'companyId': p.get('companyId'),
            'companyName': company.name if company else p.get('companyName', ''),
            'confirmOrder': p.get('confirmOrder', 0),
            'confirmAt': p.get('confirmAt'),
            'confirmedBy': p.get('confirmedBy'),
            # 拒绝确认（退回草稿）留痕：谁在什么时候因为什么拒绝了
            'rejectedAt': p.get('rejectedAt'),
            'rejectedBy': p.get('rejectedBy'),
            'rejectReason': p.get('rejectReason', ''),
        })
    return out


# 详情页最多返回的流水条数（200+ 轮修改的合同否则会返回上千条）
TIMELINE_MAX = settings.CONTRACT_TIMELINE_MAX
CHECKS_MAX = settings.CONTRACT_CHECKS_MAX


def _cap_latest(items: list, limit: int) -> tuple:
    """只保留最近 limit 条，返回 (截断后的列表, 是否被截断)。"""
    if limit <= 0 or len(items) <= limit:
        return items, False
    return items[-limit:], True


def _contract_data(contract: Contract, *, with_timeline=False, thin=False,
                   company_map=None, viewer=None) -> dict:
    """合同序列化；列表/增量走 thin=True（字段裁剪：不带 inputs 等大字段）。

    ``with_timeline`` 受审计可见范围约束（``audit_company_ids``）：参赛代表拿不到时间线与
    检查记录；系统超级管理员 / 比赛超级管理员拿全部（2026-11 起取消主席团身份）。
    """
    data = {
        'id': contract.id,
        'contractTypeKey': contract.contract_type_key,
        'pluginVersion': contract.plugin_version,
        'name': contract.name,
        'status': contract.status,
        'statusLabel': contract.get_status_display(),
        'pendingPartyIndex': contract.pending_party_index,
        'parties': _party_data(contract, company_map),
        'unifiedNumber': contract.unified_number,
        'numberedAt': contract.numbered_at.isoformat() if contract.numbered_at else None,
        'executedAt': contract.executed_at.isoformat() if contract.executed_at else None,
        'postedAt': contract.posted_at.isoformat() if contract.posted_at else None,
        'roundNo': contract.round_no,
        'overdue': contract.status in ('MOD_APPLYING', 'BACKFILL_REVIEW')
        and contract.updated_at is not None
        and (timezone.now() - contract.updated_at).total_seconds()
        > 24 * 3600,
        'isBackfill': contract.is_backfill,
        'fiscalYearId': contract.fiscal_year_id,
        'fiscalYear': contract.fiscal_year.year if contract.fiscal_year_id else None,
        'createdBy': contract.created_by,
        'createdAt': contract.created_at.isoformat(),
        'cancelledAt': contract.cancelled_at.isoformat() if contract.cancelled_at else None,
        'cancelledBy': contract.cancelled_by_username,
        'cancelReason': contract.cancel_reason,
    }
    if not thin or with_timeline:
        data['inputs'] = contract.inputs
    if with_timeline:
        scope = audit_company_ids(viewer, ctx.get_competition_id())
        if scope:
            scoped = None if '*' in scope else scope
            party_ids = {int(p['companyId']) for p in (contract.parties or [])
                         if p.get('companyId')}
            # 审计范围：'*' = 全部；空集 = 无审计可见性（参赛代表）
            if scoped is None or (scoped & party_ids):
                timeline, timeline_truncated = _cap_latest(
                    _timeline(contract, company_ids=scoped), TIMELINE_MAX)
                checks, checks_truncated = _cap_latest(
                    _checks_data(contract, company_ids=scoped), CHECKS_MAX)
                data['timeline'] = timeline
                data['timelineTruncated'] = timeline_truncated
                data['checks'] = checks
                data['checksTruncated'] = checks_truncated
    return data


def _checks_data(contract: Contract, company_ids=None) -> list:
    """检查记录（§7.3 四检查点）：含依据快照与重演值（replayBasis，上游修改后按账本链重算）。

    ``company_ids`` 非空时只保留这些公司角色对应的依据（主席团按所辖公司过滤）。
    """
    from apps.competition.contracts import ledger

    rows = ledger.annotate_checks(contract)
    if company_ids is None:
        return rows
    party_companies = {p['role']: p.get('companyId') for p in (contract.parties or [])}
    for row in rows:
        for key in ('basis', 'replayBasis'):
            row[key] = {
                role: fields for role, fields in (row.get(key) or {}).items()
                if party_companies.get(role) in company_ids
            }
    return rows


def _timeline(contract: Contract, company_ids=None) -> list:
    """确认时间线（§14.6）：谁在什么时候确认 + 设备信息 + 全流程节点。

    文案一律中文：参与方角色取插件 ``PARTY_ROLES[].label``，字段取 ``IndustryField.name``，
    操作人显示用户名（不再出现 ``buyer`` / ``cash`` / 用户 id）。
    ``company_ids`` 非空时，字段变更节点只保留这些公司的流水（主席团按所辖公司过滤）。
    """
    from django.contrib.auth import get_user_model

    from apps.common.devices import localize_snapshot
    from apps.competition.contracts import services as contract_services
    from apps.competition.industries.models import IndustryField

    # 参与方角色 → 中文名；插件缺失时退回角色键，不影响时间线
    role_labels: dict[str, str] = {}
    try:
        module = contract_services.contract_module_for(
            contract.contract_type_key, contract.plugin_version)
        for role in getattr(module, 'PARTY_ROLES', None) or []:
            key = role.get('role')
            if key:
                role_labels[key] = role.get('label') or key
    except Exception:  # noqa: BLE001
        role_labels = {}

    value_logs = list(FieldLog.objects.filter(
        contract=contract, event=FieldLog.Event.VALUE_CHANGE,
        **({'company_id__in': company_ids} if company_ids is not None else {}))[:200])
    field_names = {
        f.field_key: (f.name or f.field_key)
        for f in IndustryField.objects.filter(
            field_key__in={log.field_key for log in value_logs})
    }

    mod_requests = list(contract.mod_requests.all())
    user_ids = {contract.created_by} | {m.reviewed_by for m in mod_requests if m.reviewed_by}
    user_ids.discard(None)
    usernames = dict(
        get_user_model().objects.filter(pk__in=user_ids).values_list('id', 'username'))

    def user_label(user_id) -> str:
        if not user_id:
            return '系统'
        return usernames.get(user_id) or f'用户#{user_id}'

    nodes = [{
        'type': 'CREATED', 'at': contract.created_at.isoformat(),
        'title': '合同创建', 'actor': user_label(contract.created_by), 'detail': '',
    }]
    for c in contract.confirmations.all():
        snapshot = localize_snapshot(c.device_snapshot)
        nodes.append({
            'type': 'CONFIRM', 'at': c.confirmed_at.isoformat(),
            'title': f'参与方 {role_labels.get(c.party_role, c.party_role)} 确认',
            'actor': c.confirmed_by_username or user_label(c.confirmed_by),
            'detail': f'IP {c.ip or "-"} / 设备 {snapshot.get("browser") or "未知"}',
            'traceId': c.trace_id,
        })
    if contract.numbered_at:
        nodes.append({
            'type': 'NUMBERED', 'at': contract.numbered_at.isoformat(),
            'title': f'生成统一编号 {contract.unified_number}', 'actor': '系统', 'detail': '',
        })
    if contract.executed_at:
        nodes.append({
            'type': 'EXECUTED', 'at': contract.executed_at.isoformat(),
            'title': '自动执行', 'actor': '系统', 'detail': '执行插件逻辑，产生字段效果',
        })
    if contract.posted_at:
        nodes.append({
            'type': 'POSTED', 'at': contract.posted_at.isoformat(),
            'title': f'落账（第 {contract.round_no} 轮）', 'actor': '系统',
            'detail': '再次运行检查通过，合同落账生效',
        })
    for mod in mod_requests:
        nodes.append({
            'type': 'MOD_APPLY', 'at': mod.created_at.isoformat(),
            'title': f'申请修改（{mod.requested_by_username}）',
            'actor': mod.requested_by_username, 'detail': f'理由：{mod.reason}',
        })
        if mod.reviewed_by:
            nodes.append({
                'type': 'MOD_REVIEW', 'at': mod.updated_at.isoformat(),
                'title': f'超级管理员审核：{mod.get_status_display()}',
                'actor': user_label(mod.reviewed_by), 'detail': mod.review_note,
            })
        for a in (mod.other_party_approvals or []):
            nodes.append({
                'type': 'MOD_OTHER_PARTY',
                'at': a.get('at') or mod.updated_at.isoformat(),
                'title': f'其他方 {a.get("username")} {"通过" if a.get("approved") else "驳回"}',
                'actor': a.get('username', ''), 'detail': a.get('note', ''),
            })
    for log in value_logs:
        nodes.append({
            'type': 'FIELD', 'at': log.occurred_at.isoformat(),
            'title': f'字段 {field_names.get(log.field_key, log.field_key)} {op_label(log.op)}',
            'actor': log.operator_username,
            'detail': f'{log.before_raw} → {log.after_raw}（{log.get_source_display()}）',
            'traceId': log.trace_id,
        })
    nodes.sort(key=lambda n: n['at'])
    return nodes
