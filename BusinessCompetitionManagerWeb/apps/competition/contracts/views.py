"""合同 API（§12 合同分组、§14.6 合同详情确认时间线）。

状态机操作全部委托给 ``apps.competition.contracts.engine``（§3 转移表 T1–T10）。
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common import context as ctx
from apps.common.authority import (
    can_act_for_company, can_manage_competition, user_company_ids,
)
from apps.competition.audit import services as audit_services
from apps.competition.contracts import engine
from apps.competition.contracts.engine import ContractError
from apps.competition.contracts.models import Contract
from apps.competition.fieldlogs.models import FieldLog


def _error(message, code=400):
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


# ---------------------------------------------------------------- 序列化


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
        })
    return out


def _contract_data(contract: Contract, *, with_timeline=False, thin=False,
                   company_map=None) -> dict:
    """合同序列化；列表/增量走 thin=True（字段裁剪：不带 inputs 等大字段）。"""
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
        'isBackfill': contract.is_backfill,
        'fiscalYearId': contract.fiscal_year_id,
        'fiscalYear': contract.fiscal_year.year if contract.fiscal_year_id else None,
        'createdBy': contract.created_by,
        'createdAt': contract.created_at.isoformat(),
    }
    if not thin or with_timeline:
        data['inputs'] = contract.inputs
    if with_timeline:
        data['timeline'] = _timeline(contract)
        data['checks'] = _checks_data(contract)
    return data


def _checks_data(contract: Contract) -> list:
    """检查记录（§7.3 四检查点落库）：含依据快照（basis）与**依据重演**（replayBasis）——
    上游合同修改后，检查依据数字按账本链重算值展示（查账同步）。"""
    from apps.competition.contracts import ledger

    return ledger.annotate_checks(contract)


def _timeline(contract: Contract) -> list:
    """确认时间线（§14.6 硬性要求）：谁在什么时候点击了确认 + 设备信息 + 全流程节点。"""
    nodes = [{
        'type': 'CREATED', 'at': contract.created_at.isoformat(),
        'title': '合同创建', 'actor': str(contract.created_by), 'detail': '',
    }]
    for c in contract.confirmations.all():
        nodes.append({
            'type': 'CONFIRM', 'at': c.confirmed_at.isoformat(),
            'title': f'参与方 {c.party_role} 确认',
            'actor': c.confirmed_by_username or str(c.confirmed_by),
            'detail': f'IP {c.ip or "-"} / 设备 {(c.device_snapshot or {}).get("browser", "-")}',
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
            'title': '自动执行', 'actor': '系统', 'detail': 'apply() 产生字段效果',
        })
    if contract.posted_at:
        nodes.append({
            'type': 'POSTED', 'at': contract.posted_at.isoformat(),
            'title': f'落账（第 {contract.round_no} 轮）', 'actor': '系统',
            'detail': '再次运行检查通过，冻结合同相关资源',
        })
    for mod in contract.mod_requests.all():
        nodes.append({
            'type': 'MOD_APPLY', 'at': mod.created_at.isoformat(),
            'title': f'申请修改（{mod.requested_by_username}）',
            'actor': mod.requested_by_username, 'detail': f'理由：{mod.reason}',
        })
        if mod.reviewed_by:
            nodes.append({
                'type': 'MOD_REVIEW', 'at': mod.updated_at.isoformat(),
                'title': f'超级管理员审核：{mod.get_status_display()}',
                'actor': str(mod.reviewed_by), 'detail': mod.review_note,
            })
        for a in (mod.other_party_approvals or []):
            nodes.append({
                'type': 'MOD_OTHER_PARTY',
                'at': a.get('at') or mod.updated_at.isoformat(),
                'title': f'其他方 {a.get("username")} {"通过" if a.get("approved") else "驳回"}',
                'actor': a.get('username', ''), 'detail': a.get('note', ''),
            })
    for log in FieldLog.objects.filter(contract=contract, event=FieldLog.Event.VALUE_CHANGE)[:200]:
        nodes.append({
            'type': 'FIELD', 'at': log.occurred_at.isoformat(),
            'title': f'字段 {log.field_key} {log.op}',
            'actor': log.operator_username,
            'detail': f'{log.before_raw} → {log.after_raw}（{log.get_source_display()}）',
            'traceId': log.trace_id,
        })
    nodes.sort(key=lambda n: n['at'])
    return nodes


def _visible_contracts(request):
    """可见性过滤（DB 侧 JSONB containment + GIN 索引 idx_contract_parties_gin）。

    原实现把全表拉回 Python 过滤（2000+ 合同每请求全量读取），是「后期卡死」主因之一。
    """
    from django.db.models import Q

    ids = user_company_ids(request.user)
    qs = Contract.objects.all()
    if '*' in ids:
        return qs
    if not ids:
        return qs.none()
    q = Q()
    for company_id in sorted(ids):
        q |= Q(parties__contains=[{'companyId': int(company_id)}])
    return qs.filter(q)


# ---------------------------------------------------------------- 合同实例


class ContractListCreateView(APIView):
    """合同列表（全量）+ **增量同步**（`?updatedAfter=<ISO>` 只拉变更）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        contracts = _visible_contracts(request)
        updated_after = request.query_params.get('updatedAfter') or ''
        if updated_after:
            from django.utils.dateparse import parse_datetime

            cursor = parse_datetime(updated_after)
            if cursor is not None:
                contracts = contracts.filter(updated_at__gt=cursor)
            limit = min(int(request.query_params.get('limit', 500) or 500), 1000)
            now = timezone.now()
            rows = list(contracts.order_by('updated_at')[:limit])
            company_map = _company_map_for(rows)   # 批量解析公司（消 N+1）
            items = [_contract_data(c, thin=True, company_map=company_map) for c in rows]
            return Response({
                'items': items,
                'serverTime': now.isoformat(),   # 下次增量游标（避免客户端时钟偏差）
                'hasMore': len(rows) == limit,
                'mode': 'delta',
            })
        # 全量列表：**服务端分页 + 字段裁剪 + 批量公司映射**（2000+ 合同必备）
        page = max(int(request.query_params.get('page', 1) or 1), 1)
        page_size = min(int(request.query_params.get('pageSize', 50) or 50), 200)
        status_filter = request.query_params.get('status') or ''
        keyword = (request.query_params.get('q') or '').strip()
        if status_filter:
            contracts = contracts.filter(status=status_filter)
        if keyword:
            from django.db.models import Q

            contracts = contracts.filter(
                Q(name__icontains=keyword) | Q(unified_number__icontains=keyword))
        total = contracts.count()
        rows = list(contracts.order_by('-updated_at')[(page - 1) * page_size: page * page_size])
        company_map = _company_map_for(rows)
        return Response({
            'items': [_contract_data(c, thin=True, company_map=company_map) for c in rows],
            'total': total,
            'page': page,
            'pageSize': page_size,
        })

    def post(self, request, cid):
        """创建合同草稿（T1）；补录合同（isBackfill）进入超管审核（§3.4）。"""
        from apps.competition.fiscal.models import FiscalYear

        contract_type_key = (request.data.get('contractTypeKey') or '').strip()
        if not contract_type_key:
            return _error('缺少合同类型 contractTypeKey')
        parties = request.data.get('parties') or []
        if not any(can_act_for_company(request.user, p.get('companyId')) for p in parties):
            return _error('只能为可操作的公司创建合同', 403)

        fiscal_year = None
        fiscal_year_id = request.data.get('fiscalYearId')
        is_backfill = bool(request.data.get('isBackfill'))
        if fiscal_year_id:
            fiscal_year = get_object_or_404(FiscalYear, pk=fiscal_year_id)
        try:
            contract = engine.create_contract(
                contract_type_key=contract_type_key,
                plugin_version=request.data.get('pluginVersion') or '',
                name=request.data.get('name') or '',
                parties=parties,
                inputs=request.data.get('inputs') or {},
                user=request.user,
                is_backfill=is_backfill,
                fiscal_year=fiscal_year,
            )
        except (ContractError, ValueError) as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_CREATE', actor=request.user,
                                  target=str(contract.id), payload={'type': contract_type_key})
        return Response(_contract_data(contract), status=status.HTTP_201_CREATED)


class ContractDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk)
        return Response(_contract_data(contract, with_timeline=True,
                                       company_map=_company_map_for([contract])))


class ContractSubmitView(APIView):
    """T2：提交草稿（运行 check，保证创建即能执行）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk)
        try:
            engine.submit_contract(contract, user=request.user)
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_SUBMIT', actor=request.user, target=str(contract.id))
        return Response(_contract_data(contract, with_timeline=True,
                                       company_map=_company_map_for([contract])))


class ContractConfirmView(APIView):
    """T3/T4：按参与方顺序确认；确认链完成自动生成编号并自动执行。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk)
        index = contract.pending_party_index
        parties = sorted(contract.parties, key=lambda p: p.get('confirmOrder', 0))
        if index < len(parties) and not can_act_for_company(
                request.user, parties[index].get('companyId')):
            return _error('你无权确认当前参与方', 403)
        try:
            engine.confirm_party(contract, user=request.user,
                                 party_role=request.data.get('partyRole'))
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_CONFIRM', actor=request.user, target=str(contract.id))
        return Response(_contract_data(contract, with_timeline=True,
                                       company_map=_company_map_for([contract])))


class ContractEffectsView(APIView):
    """效果审计（§7.2）：每行标注轮次状态 + **重演值**（replayBefore/replayAfter）——
    修改上游合同后，下游合同的重演值自动重算（当时值保留为不可变审计，查账链条自洽）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        from apps.competition.contracts import ledger

        contract = get_object_or_404(Contract, pk=pk)
        return Response(ledger.annotate_effects(contract))


class ContractLedgerView(APIView):
    """资金账本链（查账）：该合同触及的 (公司, 字段) 全链——
    初始值 → 各合同节点（当时值 + 重演值 + 检查依据重演）→ 当前值。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        from apps.competition.contracts import ledger

        contract = get_object_or_404(Contract, pk=pk)
        return Response(ledger.contract_ledger(contract))


# ---------------------------------------------------------------- 修改流程（T6–T10）


class ContractRequestModifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk)
        if not any(can_act_for_company(request.user, p.get('companyId'))
                   for p in contract.parties):
            return _error('只有参与方可以申请修改', 403)
        try:
            mod = engine.request_modify(contract, user=request.user,
                                        reason=request.data.get('reason') or '')
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_MOD_APPLY', actor=request.user,
                                  target=str(contract.id), payload={'reason': mod.reason})
        return Response(_contract_data(contract, with_timeline=True,
                                       company_map=_company_map_for([contract])),
                        status=status.HTTP_201_CREATED)


class ContractModifyReviewView(APIView):
    """T7/T7'：超级管理员通过/驳回修改申请。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _error('需要超级管理员权限', 403)
        contract = get_object_or_404(Contract, pk=pk)
        approve = str(request.data.get('action') or '').lower() != 'reject'
        try:
            engine.review_modify(contract, user=request.user, approve=approve,
                                 note=request.data.get('note') or '')
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_MOD_REVIEW', actor=request.user,
                                  target=str(contract.id), payload={'approve': approve})
        return Response(_contract_data(contract, with_timeline=True,
                                       company_map=_company_map_for([contract])))


class ContractModifyOtherPartyView(APIView):
    """T8/T8'：所有其他方逐一通过（任一方驳回 → 回到落账态）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk)
        approve = str(request.data.get('action') or '').lower() != 'reject'
        try:
            engine.other_party_review(contract, user=request.user, approve=approve,
                                      note=request.data.get('note') or '')
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_MOD_OTHER_PARTY', actor=request.user,
                                  target=str(contract.id), payload={'approve': approve})
        return Response(_contract_data(contract, with_timeline=True,
                                       company_map=_company_map_for([contract])))


class ContractModifySubmitView(APIView):
    """T9/T10：修改定稿 → 回滚旧落账 → 重新检查 → 自动执行 → 根据新的内容修改落账。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk)
        try:
            engine.submit_changes(contract, user=request.user,
                                  inputs=request.data.get('inputs'),
                                  parties=request.data.get('parties'))
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_MOD_SUBMIT', actor=request.user,
                                  target=str(contract.id),
                                  payload={'roundNo': contract.round_no})
        return Response(_contract_data(contract, with_timeline=True,
                                       company_map=_company_map_for([contract])))


class ContractBackfillReviewView(APIView):
    """补录合同超管审核（§3.4：补录需超级管理员审核）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _error('需要超级管理员权限', 403)
        contract = get_object_or_404(Contract, pk=pk)
        approve = str(request.data.get('action') or '').lower() != 'reject'
        try:
            engine.review_backfill(contract, user=request.user, approve=approve,
                                   note=request.data.get('note') or '')
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_BACKFILL_REVIEW', actor=request.user,
                                  target=str(contract.id), payload={'approve': approve})
        return Response(_contract_data(contract, with_timeline=True,
                                       company_map=_company_map_for([contract])))
