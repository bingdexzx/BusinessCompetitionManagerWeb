"""合同 API（§12 合同分组、§14.6 确认时间线）；状态机操作全部委托 contracts.engine（§3 T1–T10）。

展示组装（合同序列化 / 时间线 / 检查依据）在 ``presenters``；本模块只做鉴权与状态机调用。
"""

from django.conf import settings

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import (
    audit_company_ids, can_act_for_company, can_manage_competition, user_company_ids,
)
from apps.competition.audit import services as audit_services
from apps.competition.contracts import engine
from apps.competition.contracts.engine import ContractError
from apps.competition.contracts.models import Contract
from apps.competition.contracts.presenters import _company_map_for, _contract_data


def party_role_label(contract_type_key: str, role: str) -> str:
    """角色中文名（查插件 PARTY_ROLES；查不到原样返回）。"""
    try:
        from apps.competition.contracts.services import contract_module_for

        module = contract_module_for(contract_type_key)
        for item in getattr(module, 'PARTY_ROLES', []) or []:
            if item.get('role') == role:
                return item.get('label') or role
    except Exception:  # noqa: BLE001 —— 插件缺失时不影响导出
        pass
    return role or '—'


def _require_capability(request, cid, capability: str):
    """角色权限矩阵守卫：没有该能力返回 403 响应，有则返回 None。"""
    from apps.common.capabilities import has_capability

    if not has_capability(request.user, capability, cid):
        return _error('当前角色没有该权限，请联系超级管理员', 403)
    return None


def _error(message, code=400):
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


def _visible_contracts(request):
    """可见性过滤（DB 侧 JSONB containment + GIN 索引）：不要全表拉回 Python 过滤
    （原实现每请求读 2000+ 合同，是「后期卡死」主因之一）。
    """
    from django.db.models import Q

    ids = user_company_ids(request.user)
    qs = Contract.objects.filter(deleted_at__isnull=True)
    if '*' in ids:
        return qs
    q = Q()
    has_scope = False
    for company_id in sorted(ids):
        q |= Q(parties__contains=[{'companyId': int(company_id)}])
        has_scope = True
    if _is_competition_chair(request.user):
        # 主席团创建合同时可为全部公司选参与方，因此也要能看到自己创建的合同
        q |= Q(created_by=request.user.id)
        has_scope = True
    if not has_scope:
        return qs.none()
    return qs.filter(q)


def _visible_contract_or_none(request, pk):
    """按可见性取单个合同（不可见/已删除 → None）：读接口不能裸按 pk 取，调用方按 404 返回。"""
    return _visible_contracts(request).filter(pk=pk).first()


def _is_competition_chair(user) -> bool:
    """当前比赛的主席团（比赛管理员）。"""
    from apps.common.context import get_competition_id
    from apps.global_.memberships.models import CompetitionMembership

    competition_id = get_competition_id()
    if not (user and user.is_authenticated and competition_id):
        return False
    return CompetitionMembership.objects.filter(
        user=user, competition_id=competition_id,
        identity=CompetitionMembership.Identity.ADMIN,
    ).exists()


def _is_party_actor(user, contract) -> bool:
    """是否为该合同某参与方的**可操作**者（分配公司后即队长；超级管理员/所辖管理员亦可）。"""
    return any(can_act_for_company(user, p.get('companyId')) for p in contract.parties)


class ContractListCreateView(APIView):
    """合同列表（全量）+ **增量同步**（`?updatedAfter=<ISO>` 只拉变更）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        denied = _require_capability(request, cid, 'view.contracts')
        if denied:
            return denied
        contracts = _visible_contracts(request)
        updated_after = request.query_params.get('updatedAfter') or ''
        if updated_after:
            from django.utils.dateparse import parse_datetime

            cursor = parse_datetime(updated_after)
            if cursor is not None:
                contracts = contracts.filter(updated_at__gt=cursor)
            limit = min(
                int(request.query_params.get('limit', settings.CONTRACT_SYNC_LIMIT)
                    or settings.CONTRACT_SYNC_LIMIT),
                settings.CONTRACT_SYNC_LIMIT_MAX)
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
        page_size = min(
            int(request.query_params.get('pageSize', settings.CONTRACT_PAGE_SIZE)
                or settings.CONTRACT_PAGE_SIZE),
            settings.CONTRACT_PAGE_SIZE_MAX)
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
        denied = _require_capability(request, cid, 'act.contracts')
        if denied:
            return denied
        """创建合同草稿（T1）；补录合同（isBackfill）进入超级管理员审核（§3.4）。"""
        from apps.competition.fiscal.models import FiscalYear

        contract_type_key = (request.data.get('contractTypeKey') or '').strip()
        if not contract_type_key:
            return _error('缺少合同类型 contractTypeKey')
        parties = request.data.get('parties') or []
        if not (_is_competition_chair(request.user)
                or any(can_act_for_company(request.user, p.get('companyId')) for p in parties)):
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
        denied = _require_capability(request, cid, 'view.contracts')
        if denied:
            return denied
        contract = _visible_contract_or_none(request, pk)
        if contract is None:
            return Response({'code': 404, 'message': '合同不存在或无权查看', 'details': ''},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))

    def patch(self, request, cid, pk):
        """草稿编辑：拒绝确认退回草稿后，发起方改内容再重新提交。"""
        denied = _require_capability(request, cid, 'act.contracts')
        if denied:
            return denied
        if not can_manage_competition(request.user, cid):
            contract = Contract.objects.filter(pk=pk, deleted_at__isnull=True).first()
            if contract is None:
                return _error('合同不存在或无权查看', 404)
            if not (_is_party_actor(request.user, contract)
                    or contract.created_by == request.user.id):
                return _error('只有发起方或参与方可以编辑草稿', 403)
        contract = Contract.objects.filter(pk=pk, deleted_at__isnull=True).first()
        if contract is None:
            return _error('合同不存在', 404)
        try:
            engine.update_draft(
                contract, user=request.user,
                name=request.data.get('name'),
                parties=request.data.get('parties'),
                inputs=request.data.get('inputs'),
            )
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_DRAFT_UPDATE', actor=request.user,
                                  target=str(contract.id))
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))

    def delete(self, request, cid, pk):
        denied = _require_capability(request, cid, 'act.contracts')
        if denied:
            return denied
        """软删除合同：仅回滚当前生效轮次 + 置 deleted_at（保留效果/冻结/检查/确认）。

        仅 DRAFT/EXEC_FAILED/EXECUTED/POSTED 可删（流程中态拒绝）；仅超级管理员；写审计。
        """
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '仅超级管理员可删除合同', 'details': ''},
                            status=status.HTTP_403_FORBIDDEN)
        contract = Contract.objects.filter(pk=pk, deleted_at__isnull=True).first()
        if contract is None:
            return Response({'code': 404, 'message': '合同不存在', 'details': ''},
                            status=status.HTTP_404_NOT_FOUND)

        # 2026-11：待确认 / 待执行的合同也要能清理，避免流程卡死后无法处理
        deletable = {
            Contract.Status.DRAFT, Contract.Status.EXEC_FAILED,
            Contract.Status.EXECUTED, Contract.Status.POSTED,
            Contract.Status.PENDING_PARTY, Contract.Status.PENDING_EXEC,
        }
        if contract.status not in deletable:
            return Response(
                {'code': 400,
                 'message': f'当前状态 {contract.get_status_display()} 不允许删除',
                 'details': ''},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            engine.rollback_round(contract, operator=request.user, round_no=contract.round_no)
            # 补录合同还会把结果同步到「当前值」，删除时要一并撤回
            engine.rollback_backfill_sync(contract, operator=request.user)
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


class ContractPluginDryRunView(APIView):
    """合同插件试跑：用本比赛真实公司字段跑 check/apply，只回显结果、不写库。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, key):
        if not can_manage_competition(request.user, cid):
            return _error('仅超级管理员可试跑插件', 403)
        from apps.competition.contracts.dryrun import dry_run_contract_plugin

        inputs = request.data.get('inputs') if isinstance(request.data.get('inputs'), dict) else None
        company_ids = request.data.get('companyIds')
        if not isinstance(company_ids, list):
            company_ids = None
        try:
            result = dry_run_contract_plugin(
                contract_type_key=key,
                plugin_version=request.data.get('pluginVersion') or '',
                inputs=inputs,
                company_ids=[int(c) for c in company_ids] if company_ids else None,
            )
        except ContractError as exc:
            return _error(str(exc))
        return Response(result)


class ContractSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        denied = _require_capability(request, cid, 'act.contracts')
        if denied:
            return denied
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
        denied = _require_capability(request, cid, 'act.contracts')
        if denied:
            return denied
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


class ContractTerminateView(APIView):
    """终止合同：参与方可操作者或超级管理员；已落账的先回滚当前轮次。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        denied = _require_capability(request, cid, 'act.contracts')
        if denied:
            return denied
        contract = Contract.objects.filter(pk=pk, deleted_at__isnull=True).first()
        if contract is None:
            return _error('合同不存在', 404)
        if not (can_manage_competition(request.user, cid)
                or _is_party_actor(request.user, contract)):
            return _error('只有参与方或超级管理员可以终止合同', 403)
        reason = request.data.get('reason') or ''
        try:
            engine.terminate_contract(contract, user=request.user, reason=reason)
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_TERMINATE', actor=request.user,
                                  target=str(contract.id), payload={'reason': reason})
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))


class ContractRejectView(APIView):
    """T3'：任一参与方拒绝确认 → 退回草稿，发起方可改后重提。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        denied = _require_capability(request, cid, 'act.contracts')
        if denied:
            return denied
        contract = get_object_or_404(Contract, pk=pk)
        try:
            engine.reject_party(contract, user=request.user,
                                reason=request.data.get('reason') or '')
        except engine.ContractPermissionError as exc:
            return _error(str(exc), 403)
        except ContractError as exc:
            return _error(str(exc))
        audit_services.log_action('CONTRACT_REJECT', actor=request.user,
                                  target=str(contract.id),
                                  payload={'reason': request.data.get('reason') or ''})
        return Response(_contract_data(contract, with_timeline=True, viewer=request.user,
                                       company_map=_company_map_for([contract])))


class ContractRetryExecuteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        denied = _require_capability(request, cid, 'act.contracts')
        if denied:
            return denied
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
    系统超级管理员 / 比赛超级管理员看全部。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        denied = _require_capability(request, cid, 'view.contracts')
        if denied:
            return denied
        from apps.competition.contracts import ledger

        scope = audit_company_ids(request.user, cid)
        if not scope:
            return Response({'code': 403, 'message': '仅超级管理员可操作', 'details': ''},
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
    系统超级管理员 / 比赛超级管理员看全部。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        denied = _require_capability(request, cid, 'view.contracts')
        if denied:
            return denied
        from apps.competition.contracts import ledger

        scope = audit_company_ids(request.user, cid)
        if not scope:
            return Response({'code': 403, 'message': '仅超级管理员可操作', 'details': ''},
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
        denied = _require_capability(request, cid, 'act.contracts_modify')
        if denied:
            return denied
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
            return _error('仅超级管理员可操作', 403)
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


class ContractModifySubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        denied = _require_capability(request, cid, 'act.contracts_modify')
        if denied:
            return denied
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
            return _error('仅超级管理员可操作', 403)
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
