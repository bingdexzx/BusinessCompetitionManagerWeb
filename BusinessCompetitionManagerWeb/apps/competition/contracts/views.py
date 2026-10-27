"""合同 API（§12 合同分组、§14.6 确认时间线）；状态机操作全部委托 contracts.engine（§3 T1–T10）。"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common import context as ctx
from apps.common.authority import (
    audit_company_ids, can_act_for_company, can_manage_competition, user_company_ids,
)
from apps.common.labels import op_label
from apps.competition.audit import services as audit_services
from apps.competition.contracts import engine
from apps.competition.contracts.engine import ContractError
from apps.competition.contracts.models import Contract
from apps.competition.fieldlogs.models import FieldLog


def _error(message, code=400):
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


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
                   company_map=None, viewer=None) -> dict:
    """合同序列化；列表/增量走 thin=True（字段裁剪：不带 inputs 等大字段）。

    ``with_timeline`` 受审计可见范围约束（``audit_company_ids``）：参赛代表拿不到时间线与
    检查记录；主席团只拿所辖公司相关的字段内容；系统超管 / 比赛超管拿全部。
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
        'isBackfill': contract.is_backfill,
        'fiscalYearId': contract.fiscal_year_id,
        'fiscalYear': contract.fiscal_year.year if contract.fiscal_year_id else None,
        'createdBy': contract.created_by,
        'createdAt': contract.created_at.isoformat(),
    }
    if not thin or with_timeline:
        data['inputs'] = contract.inputs
    if with_timeline:
        scope = audit_company_ids(viewer, ctx.get_competition_id())
        if scope:
            scoped = None if '*' in scope else scope
            party_ids = {int(p['companyId']) for p in (contract.parties or [])
                         if p.get('companyId')}
            # 主席团：只在其所辖公司与本合同当事公司有交集时才给审计信息（且只给交集部分）
            if scoped is None or (scoped & party_ids):
                data['timeline'] = _timeline(contract, company_ids=scoped)
                data['checks'] = _checks_data(contract, company_ids=scoped)
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
            'detail': '再次运行检查通过，冻结合同相关资源',
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


def _visible_contracts(request):
    """可见性过滤（DB 侧 JSONB containment + GIN 索引）：不要全表拉回 Python 过滤
    （原实现每请求读 2000+ 合同，是「后期卡死」主因之一）。
    """
    from django.db.models import Q

    ids = user_company_ids(request.user)
    qs = Contract.objects.filter(deleted_at__isnull=True)
    if '*' in ids:
        return qs
    if not ids:
        return qs.none()
    q = Q()
    for company_id in sorted(ids):
        q |= Q(parties__contains=[{'companyId': int(company_id)}])
    return qs.filter(q)


def _visible_contract_or_none(request, pk):
    """按可见性取单个合同（不可见/已删除 → None）：读接口不能裸按 pk 取，调用方按 404 返回。"""
    return _visible_contracts(request).filter(pk=pk).first()


def _is_party_actor(user, contract) -> bool:
    """是否为该合同某参与方的**可操作**者（分配公司后即队长；超管/所辖管理员亦可）。"""
    return any(can_act_for_company(user, p.get('companyId')) for p in contract.parties)


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
        contract = _visible_contract_or_none(request, pk)
        if contract is None:
            return Response({'code': 404, 'message': '合同不存在或无权查看', 'details': ''},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))

    def delete(self, request, cid, pk):
        """软删除合同：仅回滚当前生效轮次 + 置 deleted_at（保留效果/冻结/检查/确认）。

        仅 DRAFT/EXEC_FAILED/EXECUTED/POSTED 可删（流程中态拒绝）；仅超管；写审计。
        """
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '仅超级管理员可删除合同', 'details': ''},
                            status=status.HTTP_403_FORBIDDEN)
        contract = Contract.objects.filter(pk=pk, deleted_at__isnull=True).first()
        if contract is None:
            return Response({'code': 404, 'message': '合同不存在', 'details': ''},
                            status=status.HTTP_404_NOT_FOUND)

        deletable = {
            Contract.Status.DRAFT, Contract.Status.EXEC_FAILED,
            Contract.Status.EXECUTED, Contract.Status.POSTED,
        }
        if contract.status not in deletable:
            return Response(
                {'code': 400,
                 'message': f'当前状态 {contract.get_status_display()} 不允许删除',
                 'details': ''},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            engine.rollback_round(contract, operator=request.user, round_no=contract.round_no)
            if contract.effects.filter(round_no=contract.round_no).exists():
                engine.unfreeze_contract(contract, reason='合同删除')
        except ContractError as exc:
            return Response({'code': 400, 'message': str(exc), 'details': ''},
                            status=status.HTTP_400_BAD_REQUEST)

        contract_id = contract.id
        type_key = contract.contract_type_key
        number = contract.unified_number
        round_no = contract.round_no
        contract.deleted_at = timezone.now()
        contract.save(update_fields=['deleted_at', 'updated_at'])
        audit_services.log_action(
            'CONTRACT_DELETE', actor=request.user, target=str(contract_id),
            payload={'contractTypeKey': type_key, 'unifiedNumber': number,
                     'rolledBackRound': round_no})
        return Response({'ok': True, 'id': contract_id, 'rolledBackRound': round_no})


class ContractSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk)
        if not _is_party_actor(request.user, contract):
            return _error('只有参与方（公司队长/所辖管理员）可以提交该合同', 403)
        try:
            engine.submit_contract(contract, user=request.user)
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_SUBMIT', actor=request.user, target=str(contract.id))
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
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
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))


class ContractRetryExecuteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk, deleted_at__isnull=True)
        if not any(can_act_for_company(request.user, p.get('companyId'))
                   for p in contract.parties):
            return _error('只有参与方可以重试执行', 403)
        try:
            engine.retry_execute(contract, user=request.user)
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_RETRY_EXECUTE', actor=request.user,
                                  target=str(contract.id))
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))


class ContractEffectsView(APIView):
    """效果审计（§7.2）：每行带轮次状态与重演值（replayBefore/replayAfter，上游修改后重算）。

    可见范围按 ``audit_company_ids``：参赛代表不可见；主席团只看所辖公司的行；
    系统超管 / 比赛超管看全部。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        from apps.competition.contracts import ledger

        scope = audit_company_ids(request.user, cid)
        if not scope:
            return Response({'code': 403, 'message': '需要管理员权限', 'details': ''},
                            status=status.HTTP_403_FORBIDDEN)
        contract = _visible_contract_or_none(request, pk)
        if contract is None:
            return Response({'code': 404, 'message': '合同不存在或无权查看', 'details': ''},
                            status=status.HTTP_404_NOT_FOUND)
        rows = ledger.annotate_effects(contract)
        if '*' not in scope:
            rows = [row for row in rows if row['companyId'] in scope]
        return Response(rows)


class ContractLedgerView(APIView):
    """资金账本链（查账）：(公司, 字段) 全链——初始值 → 各合同节点（当时值+重演值）→ 当前值。

    可见范围按 ``audit_company_ids``：参赛代表不可见；主席团只看所辖公司的链；
    系统超管 / 比赛超管看全部。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        from apps.competition.contracts import ledger

        scope = audit_company_ids(request.user, cid)
        if not scope:
            return Response({'code': 403, 'message': '需要管理员权限', 'details': ''},
                            status=status.HTTP_403_FORBIDDEN)
        contract = _visible_contract_or_none(request, pk)
        if contract is None:
            return Response({'code': 404, 'message': '合同不存在或无权查看', 'details': ''},
                            status=status.HTTP_404_NOT_FOUND)
        data = ledger.contract_ledger(contract)
        if '*' not in scope:
            data['chains'] = [c for c in data.get('chains', []) if c['companyId'] in scope]
        return Response(data)


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
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
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
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))


class ContractModifyOtherPartyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk)
        approve = str(request.data.get('action') or '').lower() != 'reject'
        try:
            engine.other_party_review(contract, user=request.user, approve=approve,
                                      note=request.data.get('note') or '')
        except engine.ContractPermissionError as exc:
            return _error(str(exc), 403)
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_MOD_OTHER_PARTY', actor=request.user,
                                  target=str(contract.id), payload={'approve': approve})
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))


class ContractModifySubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        contract = get_object_or_404(Contract, pk=pk)
        if not _is_party_actor(request.user, contract):
            return _error('只有参与方（公司队长/所辖管理员）可以提交修改', 403)
        try:
            engine.submit_changes(contract, user=request.user,
                                  inputs=request.data.get('inputs'),
                                  parties=request.data.get('parties'))
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_MOD_SUBMIT', actor=request.user,
                                  target=str(contract.id),
                                  payload={'roundNo': contract.round_no})
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))


class ContractBackfillReviewView(APIView):
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
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))
