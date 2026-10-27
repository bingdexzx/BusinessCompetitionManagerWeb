"""股票 API（契约 §4：行情与交易 + 快照/增量同步协议）。

路由（挂在 /api/ 前缀，见 urls.py）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /stock/stocks | 股票列表（薄字段，?page&pageSize 分页） |
| GET | /stock/stocks/{code} | 单股详情（含指标全字段） |
| GET | /stock/stocks/{code}/candles | K 线（?fromRound&limit keyset 分页） |
| GET | /stock/book | 我的持仓 + 资金账户 |
| POST | /stock/orders | 下单 {code, side, price, quantity}（校验现金/持仓） |
| DELETE | /stock/orders/{id} | 撤单（仅 PENDING 且本人） |
| GET | /stock/orders | 我的委托（?status，分页） |
| POST | /stock/round/advance | 推进轮次（超管） |
| GET | /stock/market | 市场概览（轻量心跳） |
| GET | /stock/sync | 快照+增量同步（§4.2） |

权限（契约 §4 / 任务口径；2026-10 决策：队员只读、操作仅队长）：
- 查看行情（含 sync/book/orders/holdings 读）= 任何比赛成员；本公司数据队长与队员都能看；
- 下单/撤单 = **可操作**本公司者（COMPANY 账户 can_act_for_company —— 分配公司后仅队长；
  USER 账户=本人）；
- advance = 超管（apps.common.authority.can_manage_competition）。

错误响应统一 ``{'code', 'message', 'details'}``（参考 contracts/views._error）。
"""

from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import (
    can_act_for_company,
    can_manage_competition,
    user_company_ids,
    user_membership,
    user_operable_company_ids,
)
from apps.competition.audit import services as audit_services

from .engine import (
    StockError,
    advance_round,
    resolve_effective_pbs,
    resolve_field_value_map,
    resolve_field_value_or_default,
    round2,
)
from .models import (
    Stock, StockCandle, StockFundsAccount, StockHolding, StockOrder,
)
from .services import (
    account_owned_by_user,
    build_last_candle_map,
    build_sync_payload,
    owner_account_q,
    serialize_account,
    serialize_candle,
    serialize_holding,
    serialize_order,
    serialize_stock_detail,
    serialize_stock_thin,
)

# 委托最小值（旧 CreateOrderSerializer：price/quantity min_value=0.0001）
DECIMAL_MIN = Decimal('0.0001')


def _error(message, code=400, details=''):
    """统一业务错误响应（契约 §4 任务口径：{'code','message','details'}）。"""
    return Response({'code': code, 'message': message, 'details': details}, status=code)


# ---------------------------------------------------------------- 权限


def _require_member(user, cid):
    """查看行情权限：任何比赛成员（§4 任务口径）；系统超管恒通过。"""
    if user is not None and user.is_authenticated:
        if user.is_superuser:
            return True
        if user_membership(user, cid) is not None:
            return True
        if user_company_ids(user, cid):
            return True
    return False


def _pagination(request, default_size=50, max_size=500):
    """薄分页（§4.1 ?page&pageSize；§5 表格 50/页）。"""
    try:
        page = max(1, int(request.query_params.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.query_params.get('pageSize', default_size))
    except (TypeError, ValueError):
        page_size = default_size
    page_size = max(1, min(max_size, page_size))
    return page, page_size, (page - 1) * page_size


def _page_envelope(items, total, page, page_size):
    return {'items': items, 'total': total, 'page': page, 'pageSize': page_size}


def _parse_decimal(raw, field, *, min_value=None):
    """金额/数量入参解析（Decimal 口径，拒绝非法值；旧 CreateOrderSerializer 语义）。"""
    if raw is None or raw == '':
        raise StockError(f'缺少参数 {field}')
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise StockError(f'{field} 不是合法数值')
    if not value.is_finite():
        raise StockError(f'{field} 不是合法数值')
    if min_value is not None and value < min_value:
        raise StockError(f'{field} 不能小于 {min_value}')
    return value


# ---------------------------------------------------------------- 行情


class StockListView(APIView):
    """GET /stock/stocks —— 股票列表（薄字段：code/name/currentPrice/initPrice/
    round/updatedAt/涨跌幅，§4.1）；``?page&pageSize`` 分页。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _error('需要比赛成员身份', 403)
        page, page_size, offset = _pagination(request)
        qs = Stock.objects.all().order_by('code')
        total = qs.count()
        rows = list(qs[offset:offset + page_size])
        candle_map = build_last_candle_map([s.id for s in rows])
        items = [
            serialize_stock_thin(
                s, float(candle_map[s.id].change_pct) if s.id in candle_map else 0.0,
            )
            for s in rows
        ]
        return Response(_page_envelope(items, total, page, page_size))

    def post(self, request, cid):
        """新增股票（超管）：code/name 必填，价格与股本用 Decimal（旧「新增股票」语义）。"""
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        stock = Stock()
        try:
            _apply_stock_fields(stock, request.data, creating=True)
        except StockError as exc:
            return _error(str(exc))
        if Stock.objects.filter(code=stock.code).exists():
            return _error(f'股票代码 {stock.code} 已存在')
        stock.save()
        return Response(_serialize_stock_admin(stock), status=status.HTTP_201_CREATED)


class StockDetailView(APIView):
    """GET /stock/stocks/{code} —— 单股详情（含指标全字段，§4.1）；
    PATCH/DELETE —— 股票维护（超管；有挂单/持仓拒绝删除，旧系统语义）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, code):
        if not _require_member(request.user, cid):
            return _error('需要比赛成员身份', 403)
        stock = Stock.objects.filter(code=code).first()
        if stock is None:
            return _error('股票不存在', 404)
        field_map = resolve_field_value_map(cid)
        pb_map = resolve_effective_pbs([stock])
        candle = build_last_candle_map([stock.id]).get(stock.id)
        return Response(serialize_stock_detail(
            stock, field_map=field_map, pb_map=pb_map, candle=candle,
        ))

    def patch(self, request, cid, code):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        stock = Stock.objects.filter(code=code).first()
        if stock is None:
            return _error('股票不存在', 404)
        try:
            _apply_stock_fields(stock, request.data, creating=False)
        except StockError as exc:
            return _error(str(exc))
        if 'code' in request.data and Stock.objects.filter(code=stock.code).exclude(pk=stock.pk).exists():
            return _error(f'股票代码 {stock.code} 已存在')
        stock.save()
        return Response(_serialize_stock_admin(stock))

    def delete(self, request, cid, code):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        stock = Stock.objects.filter(code=code).first()
        if stock is None:
            return _error('股票不存在', 404)
        # 旧系统语义：有挂单或持仓拒绝删除
        if StockOrder.objects.filter(stock=stock).exists():
            return _error('该股票存在委托单，不能删除')
        if StockHolding.objects.filter(stock=stock).exists():
            return _error('该股票存在持仓，不能删除')
        stock.delete()
        return Response({'ok': True})


class StockCandlesView(APIView):
    """GET /stock/stocks/{code}/candles —— K 线（``?fromRound&limit`` keyset 分页，
    按需加载，§4.1）。keyset 语义：只取 round > fromRound 的升序前 limit 条，
    不用 OFFSET（§1 大表查询）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, code):
        if not _require_member(request.user, cid):
            return _error('需要比赛成员身份', 403)
        stock = Stock.objects.filter(code=code).first()
        if stock is None:
            return _error('股票不存在', 404)
        try:
            from_round = int(request.query_params.get('fromRound') or 0)
        except (TypeError, ValueError):
            return _error('fromRound 不是合法整数')
        try:
            limit = int(request.query_params.get('limit') or 200)
        except (TypeError, ValueError):
            limit = 200
        limit = max(1, min(2000, limit))

        qs = StockCandle.objects.filter(stock_id=stock.id, round__gt=from_round).order_by('round')
        rows = list(qs[:limit + 1])
        has_more = len(rows) > limit
        rows = rows[:limit]
        return Response({
            'items': [serialize_candle(c, stock_code=stock.code) for c in rows],
            'hasMore': has_more,
            'nextFromRound': rows[-1].round if rows else from_round,
        })


class MarketView(APIView):
    """GET /stock/market —— 市场概览：{round, stockCount, updatedAt}（轻量心跳，§4.1）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _error('需要比赛成员身份', 403)
        from django.db.models import Max

        agg = Stock.objects.aggregate(m=Max('round'), u=Max('updated_at'))
        return Response({
            'round': agg['m'] or 0,
            'stockCount': Stock.objects.count(),
            'updatedAt': agg['u'].isoformat() if agg['u'] else None,
        })


# ---------------------------------------------------------------- 我的账户与持仓


def _visible_accounts_q(user, cid):
    owner_q, _ = owner_account_q(user, cid)
    return owner_q


class BookView(APIView):
    """GET /stock/book —— 我的持仓 + 资金账户（owner 匹配 user 或本队/所辖公司，§4.1）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _error('需要比赛成员身份', 403)
        owner_q = _visible_accounts_q(request.user, cid)
        accounts = list(StockFundsAccount.objects.filter(owner_q).order_by('id'))
        account_data = []
        for a in accounts:
            field_balance = None
            if a.bind_field_id is not None and a.company_id is not None:
                field_balance = resolve_field_value_or_default(a.company_id, a.bind_field_id)
            account_data.append(serialize_account(a, field_balance=field_balance))

        holdings = list(
            StockHolding.objects.select_related('stock')
            .filter(funds_account__in=[a.id for a in accounts] or [-1])
            .order_by('id')
        )
        holding_data = [
            serialize_holding(
                h,
                stock_code=h.stock.code,
                stock_name=h.stock.name,
                current_price=h.stock.current_price,
            )
            for h in holdings
        ]
        return Response({'accounts': account_data, 'holdings': holding_data})


# ---------------------------------------------------------------- 委托


def _resolve_order_account(user, cid, stock, explicit_id):
    """解析下单资金账户（契约 §4.1 下单体只有 {code, side, price, quantity}）。

    1. 显式 fundsAccountId → 直接用（仍校验归属）；
    2. 否则优先股票所属公司的 COMPANY 账户（can_act_for_company「可操作」时 ——
       分配公司后仅队长可操作，队员下单会落到自己的 USER 账户）；
    3. 否则本人 USER 账户。
    """
    if explicit_id is not None:
        account = StockFundsAccount.objects.filter(pk=explicit_id).first()
        if account is None:
            raise StockError('资金账户不存在', code=404, status_code=404)
        return account
    if stock.company_id and can_act_for_company(user, stock.company_id, cid):
        account = (
            StockFundsAccount.objects
            .filter(owner_type='COMPANY', company_id=stock.company_id)
            .order_by('id').first()
        )
        if account is not None:
            return account
    account = (
        StockFundsAccount.objects
        .filter(owner_type='USER', user_id=user.id)
        .order_by('id').first()
    )
    if account is not None:
        return account
    raise StockError('没有可用的资金账户')


class OrderListCreateView(APIView):
    """GET /stock/orders —— 我的委托（?status，分页，§4.1）；
    POST /stock/orders —— 下单 {code, side, price, quantity}（校验现金/持仓）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _error('需要比赛成员身份', 403)
        owner_q, _ = owner_account_q(request.user, cid)
        qs = StockOrder.objects.select_related('stock').filter(
            funds_account__in=StockFundsAccount.objects.filter(owner_q),
        )
        status_filter = (request.query_params.get('status') or '').strip().upper()
        if status_filter:
            qs = qs.filter(status=status_filter)
        page, page_size, offset = _pagination(request)
        total = qs.count()
        rows = list(qs.order_by('-updated_at', '-id')[offset:offset + page_size])
        items = [serialize_order(o, stock_code=o.stock.code) for o in rows]
        return Response(_page_envelope(items, total, page, page_size))

    def post(self, request, cid):
        if not _require_member(request.user, cid):
            return _error('需要比赛成员身份', 403)
        code = (request.data.get('code') or '').strip()
        side = (request.data.get('side') or '').strip().upper()
        if side not in ('BUY', 'SELL'):
            return _error('side 必须是 BUY 或 SELL')
        stock = Stock.objects.filter(code=code).first()
        if stock is None:
            return _error('股票不存在', 404)

        try:
            price = _parse_decimal(request.data.get('price'), 'price', min_value=DECIMAL_MIN)
            quantity = _parse_decimal(request.data.get('quantity'), 'quantity', min_value=DECIMAL_MIN)
            explicit_id = request.data.get('fundsAccountId')
            if explicit_id is not None and explicit_id != '':
                explicit_id = int(explicit_id)
            else:
                explicit_id = None
            account = _resolve_order_account(request.user, cid, stock, explicit_id)
        except StockError as exc:
            return _error(str(exc), exc.code)
        except (TypeError, ValueError):
            return _error('fundsAccountId 不是合法整数')

        # 下单 = 操作：COMPANY 账户要求「可操作」本公司（分配公司后仅队长；队员只读）
        if not account_owned_by_user(
            account, request.user, user_operable_company_ids(request.user, cid),
        ):
            return _error('无权操作该资金账户', 403)

        try:
            order = _create_order(request.user, cid, stock, account, side, price, quantity)
        except StockError as exc:
            return _error(str(exc), exc.code)
        audit_services.log_action(
            'STOCK_ORDER_CREATE', actor=request.user, target=str(order.id),
            payload={'code': code, 'side': side, 'price': str(price), 'quantity': str(quantity)},
        )
        return Response(
            serialize_order(order, stock_code=stock.code), status=status.HTTP_201_CREATED,
        )


def _create_order(user, cid, stock, account, side, price, quantity):
    """下单事务（旧 OrderCollectionView.post 语义）：

    - 委托价限制：不得超过当前价 ±10%（Decimal 域）；
    - select_for_update 锁账户行防并发超买超卖；
    - 已挂未成交占用：买占用现金、卖占用持仓（同一账户多笔挂单合计校验）；
    - 单事务创建 PENDING 委托（契约 §1 并发写：撮合/落账单事务 + 行锁）。
    """
    from .engine import comp_atomic

    price_limit = stock.current_price * Decimal('0.1')
    upper_limit = (stock.current_price + price_limit).quantize(Decimal('0.01'))
    lower_limit = (stock.current_price - price_limit).quantize(Decimal('0.01'))
    if price > upper_limit + Decimal('0.001'):
        raise StockError(f'委托价不能超过 ￥{upper_limit}（当前价 ￥{stock.current_price} 的 +10%）')
    if price < lower_limit - Decimal('0.001'):
        raise StockError(f'委托价不能低于 ￥{lower_limit}（当前价 ￥{stock.current_price} 的 -10%）')

    with comp_atomic():
        locked_account = StockFundsAccount.objects.select_for_update().get(pk=account.id)

        available_balance = locked_account.cash_balance
        if locked_account.bind_field_id and locked_account.company_id:
            v = resolve_field_value_or_default(
                locked_account.company_id, locked_account.bind_field_id,
            )
            if v is not None:
                available_balance = v

        pending = StockOrder.objects.filter(
            funds_account_id=locked_account.id, stock_id=stock.id, status='PENDING',
        )
        pending_buy_cost = Decimal('0')
        pending_sell_shares = Decimal('0')
        for o in pending:
            if o.side == 'BUY':
                pending_buy_cost += Decimal(str(o.price)) * Decimal(str(o.quantity))
            else:
                pending_sell_shares += Decimal(str(o.quantity))

        if side == 'BUY':
            need = price * quantity
            if Decimal(str(available_balance)) < need + pending_buy_cost - Decimal('0.000001'):
                raise StockError('现金余额不足')
        else:
            holding = StockHolding.objects.filter(
                funds_account_id=locked_account.id, stock_id=stock.id,
            ).first()
            available_shares = Decimal(str(holding.shares if holding else 0)) - pending_sell_shares
            if available_shares < quantity - Decimal('0.000001'):
                raise StockError('持仓不足')

        return StockOrder.objects.create(
            stock_id=stock.id,
            funds_account_id=locked_account.id,
            side=side,
            price=price,
            quantity=quantity,
            amount=round2(price * quantity),
            status='PENDING',
            round=stock.round,
        )


class OrderItemView(APIView):
    """DELETE /stock/orders/{id} —— 撤单（仅 PENDING 且本人/所辖公司，§4.1）。"""

    permission_classes = [IsAuthenticated]

    def delete(self, request, cid, pk):
        if not _require_member(request.user, cid):
            return _error('需要比赛成员身份', 403)
        from .engine import comp_atomic

        with comp_atomic():
            # P0-#1: select_for_update 锁定订单行，防止撤单与撮合引擎并发竞态
            order = StockOrder.objects.select_for_update().filter(pk=pk).first()
            if order is None:
                return _error('订单不存在', 404)
            account = StockFundsAccount.objects.filter(pk=order.funds_account_id).first()
            if account is None:
                return _error('资金账户不存在', 404)
            # 撤单 = 操作：同上，COMPANY 账户要求「可操作」本公司
            if not account_owned_by_user(
                account, request.user, user_operable_company_ids(request.user, cid),
            ):
                return _error('无权操作该资金账户', 403)
            if order.status != 'PENDING':
                return _error('仅可撤销挂单')
            order.status = 'CANCELLED'
            order.save(update_fields=['status'])
        audit_services.log_action(
            'STOCK_ORDER_CANCEL', actor=request.user, target=str(order.id),
        )
        return Response({'id': order.id, 'status': order.status})


# ---------------------------------------------------------------- 推进轮次（§4.1）


class AdvanceRoundView(APIView):
    """POST /stock/round/advance —— 推进轮次（超管，can_manage_competition，§4.1）。

    撮合 + 定价 + K 线 + 做市商报价，单事务（engine.advance_round，§3）；
    成功后由 engine 广播 stock-updated 推送信号（§4.3）。
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _error('需要超级管理员权限', 403)
        data = request.data or {}
        stock_ids = data.get('stockIds')
        if stock_ids is not None:
            try:
                stock_ids = [int(x) for x in stock_ids]
            except (TypeError, ValueError):
                return _error('stockIds 不是合法整数列表')
        try:
            result = advance_round(
                competition_id=cid,
                stock_ids=stock_ids,
                market_maker=data.get('marketMaker'),
                stock_config=data.get('stockConfig'),
                operator=request.user,
            )
        except StockError as exc:
            return _error(str(exc), exc.code)
        # 审计已在 engine.advance_round 内以 operator=request.user 记录（STOCK_ADVANCE_ROUND）
        return Response(result)


# ---------------------------------------------------------------- 同步协议（§4.2）


class SyncView(APIView):
    """GET /stock/sync —— 快照 + 增量同步（契约 §4.2，核心性能项）。

    - ``?since=<ISO时间|空>&limit=<默认500>``：since 空 → snapshot（全量薄字段，
      仍分页 limit）；带 since → delta（各集合 updated_at > since，
      ORDER BY updated_at, id keyset，limit 截断置 hasMore）；
    - 响应：{mode, serverTime, round, hasMore, stocks, candles, orders, holdings, accounts}；
      游标永远用上一响应的 serverTime（规避客户端时钟偏差）；
    - 可见性裁剪：orders/holdings/accounts 只返回我的（user 或所辖公司）；
      stocks/candles 全员可见。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return _error('需要比赛成员身份', 403)
        payload = build_sync_payload(
            user=request.user,
            since_raw=request.query_params.get('since'),
            limit_raw=request.query_params.get('limit'),
            competition_id=cid,
        )
        return Response(payload)


# ================================================================ 管理端（新增·编辑·删除）
# 旧系统「新增股票 / 新增资金账户」能力移植：行情/交易页只读，维护入口在这里（超管）。


_STOCK_DECIMAL_FIELDS = {
    'totalShares': 'total_shares', 'initNetProfit': 'init_net_profit',
    'initPrice': 'init_price', 'currentPrice': 'current_price',
}
_STOCK_FLOAT_FIELDS = {
    'industryPe': 'industry_pe', 'currentCarbon': 'current_carbon',
    'industryAvgCarbon': 'industry_avg_carbon', 'happiness': 'happiness',
    'pbRandom': 'pb_random',
}
_STOCK_TEXT_FIELDS = {
    'carbonFieldRef': 'carbon_field_ref', 'happinessFieldRef': 'happiness_field_ref',
    'industryAvgCarbonRefs': 'industry_avg_carbon_refs',
}
_STOCK_INT_FIELDS = {'pbCompanyId': 'pb_company_id', 'pbFieldId': 'pb_field_id'}


def _apply_stock_fields(stock, data: dict, *, creating: bool):
    """把管理端入参写入 Stock（Decimal 精度口径；缺省 currentPrice=initPrice）。"""
    if creating or 'code' in data:
        code = str(data.get('code') or '').strip()
        if not code:
            raise StockError('缺少参数 code')
        stock.code = code
    if creating or 'name' in data:
        name = str(data.get('name') or '').strip()
        if not name:
            raise StockError('缺少参数 name')
        stock.name = name
    for api_key, model_field in _STOCK_DECIMAL_FIELDS.items():
        if api_key in data and data.get(api_key) not in (None, ''):
            setattr(stock, model_field, _parse_decimal(data.get(api_key), api_key))
    if creating and stock.current_price is None:
        stock.current_price = stock.init_price  # 未给现价时以发行价起步
    for api_key, model_field in _STOCK_FLOAT_FIELDS.items():
        if api_key in data and data.get(api_key) not in (None, ''):
            try:
                setattr(stock, model_field, float(data.get(api_key)))
            except (TypeError, ValueError):
                raise StockError(f'{api_key} 不是合法数值')
    for api_key, model_field in _STOCK_TEXT_FIELDS.items():
        if api_key in data:
            setattr(stock, model_field, str(data.get(api_key) or ''))
    for api_key, model_field in _STOCK_INT_FIELDS.items():
        if api_key not in data:
            continue
        raw = data.get(api_key)
        if raw in (None, ''):
            setattr(stock, model_field, None)  # 显式置空 = 清除关联
            continue
        try:
            setattr(stock, model_field, int(raw))
        except (TypeError, ValueError):
            raise StockError(f'{api_key} 不是合法整数')
    if 'companyId' in data:
        stock.company_id = data.get('companyId') or None
    if creating:
        stock.industry_pe = stock.industry_pe or 0.0
        stock.current_carbon = stock.current_carbon or 0.0
        stock.industry_avg_carbon = stock.industry_avg_carbon or 0.0
        stock.happiness = stock.happiness or 0.0


def _serialize_stock_admin(stock) -> dict:
    return {
        'id': stock.id, 'code': stock.code, 'name': stock.name,
        'totalShares': stock.total_shares, 'initNetProfit': stock.init_net_profit,
        'industryPe': stock.industry_pe, 'currentCarbon': stock.current_carbon,
        'industryAvgCarbon': stock.industry_avg_carbon, 'happiness': stock.happiness,
        'initPrice': stock.init_price, 'currentPrice': stock.current_price,
        'round': stock.round, 'companyId': stock.company_id,
        'pbCompanyId': stock.pb_company_id, 'pbFieldId': stock.pb_field_id,
        'pbRandom': stock.pb_random,
        'carbonFieldRef': stock.carbon_field_ref,
        'happinessFieldRef': stock.happiness_field_ref,
        'industryAvgCarbonRefs': stock.industry_avg_carbon_refs,
    }


def _serialize_account_admin(account) -> dict:
    return {
        'id': account.id, 'name': account.name, 'ownerType': account.owner_type,
        'companyId': account.company_id, 'userId': account.user_id,
        'cashBalance': account.cash_balance, 'bindFieldId': account.bind_field_id,
    }


class AccountListCreateView(APIView):
    """GET/POST /stock/accounts —— 资金账户管理（超管）：新增资金账户（旧系统语义）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        accounts = StockFundsAccount.objects.all().order_by('id')
        return Response({'items': [_serialize_account_admin(a) for a in accounts],
                         'total': accounts.count()})

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        name = str(request.data.get('name') or '').strip()
        if not name:
            return _error('缺少参数 name')
        owner_type = request.data.get('ownerType') or 'USER'
        if owner_type not in ('USER', 'COMPANY'):
            return _error('ownerType 应为 USER 或 COMPANY')
        if owner_type == 'USER' and not request.data.get('userId'):
            return _error('USER 账户缺少 userId')
        if owner_type == 'COMPANY' and not request.data.get('companyId'):
            return _error('COMPANY 账户缺少 companyId')
        if StockFundsAccount.objects.filter(name=name).exists():
            return _error(f'账户名 {name} 已存在')
        account = StockFundsAccount(
            name=name, owner_type=owner_type,
            user_id=request.data.get('userId') or None,
            company_id=request.data.get('companyId') or None,
            bind_field_id=request.data.get('bindFieldId') or None,
        )
        if request.data.get('cashBalance') not in (None, ''):
            account.cash_balance = _parse_decimal(request.data.get('cashBalance'),
                                                  'cashBalance')
        account.save()
        return Response(_serialize_account_admin(account), status=status.HTTP_201_CREATED)


class AccountItemView(APIView):
    """PATCH/DELETE /stock/accounts/{id} —— 资金账户维护（超管）。"""

    permission_classes = [IsAuthenticated]

    def patch(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        account = StockFundsAccount.objects.filter(pk=pk).first()
        if account is None:
            return _error('账户不存在', 404)
        if 'name' in request.data:
            name = str(request.data.get('name') or '').strip()
            if not name:
                return _error('账户名必填')
            if StockFundsAccount.objects.filter(name=name).exclude(pk=pk).exists():
                return _error(f'账户名 {name} 已存在')
            account.name = name
        if 'ownerType' in request.data:
            owner_type = request.data.get('ownerType')
            if owner_type not in ('USER', 'COMPANY'):
                return _error('ownerType 应为 USER 或 COMPANY')
            account.owner_type = owner_type
        for key, field in (('userId', 'user_id'), ('companyId', 'company_id'),
                           ('bindFieldId', 'bind_field_id')):
            if key in request.data:
                setattr(account, field, request.data.get(key) or None)
        if request.data.get('cashBalance') not in (None, ''):
            account.cash_balance = _parse_decimal(request.data.get('cashBalance'),
                                                  'cashBalance')
        account.save()
        return Response(_serialize_account_admin(account))

    def delete(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _error('没有权限执行此操作', 403)
        account = StockFundsAccount.objects.filter(pk=pk).first()
        if account is None:
            return _error('账户不存在', 404)
        if StockOrder.objects.filter(funds_account=account).exists():
            return _error('该账户存在委托单，不能删除')
        if StockHolding.objects.filter(funds_account=account).exists():
            return _error('该账户存在持仓，不能删除')
        account.delete()
        return Response({'ok': True})
