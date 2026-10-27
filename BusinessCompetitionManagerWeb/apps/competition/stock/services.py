"""股票服务层：**快照 + 增量同步协议**序列化（契约 §4.2）+ 推送信号（§4.3）。

语义来源：《股票模块与同步优化.md》§4.2 / §4.3；序列化字段与旧系统
backend/apps/stock/views.py::_serialize_stock / _serialize_account 对齐（camelCase）。

设计原则（§1 字段裁剪 / §4.2）：
- 列表与增量只带**薄字段**（不含描述/大 JSON）；详情才给指标全字段；
- 序列化函数全部**纯函数**（鸭子类型读属性，不触库），便于不依赖 DB 单测；
- 组装查询的入口 :func:`build_sync_payload` 负责 keyset 分页（ORDER BY updated_at, id）
  与可见性裁剪（orders/holdings/accounts 只回本人的，§4.2）。
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django.utils.dateparse import parse_datetime

# 同步协议参数（§4.2：limit 默认 500）
SYNC_DEFAULT_LIMIT = 500
SYNC_MAX_LIMIT = 2000

# 业务错误统一用 engine.StockError（契约 §3 适配点 1）；此处转口便于服务层引用。
# engine 仅在函数内延迟导入本模块（见 advance_round），故模块级导入不会循环。
from .engine import StockError  # noqa: E402,F401


# ================================================================ 推送信号（§4.3）


def broadcast_stock_updated(competition_id, round_no: int) -> None:
    """轮次推进/成交后广播：``{'type': 'stock-updated', 'round': N, 'serverTime': ...}``。

    §4.3 防风暴：**推送只当信号，不带数据**；客户端收到后去抖合并成一次
    /stock/sync 增量拉取。实现按任务口径：直接复用
    ``apps.global_.messages.services._push`` 的推送模式，遍历本比赛
    CompetitionMembership 成员 user_id 逐个推送，**失败静默**不影响业务。
    """
    try:
        from apps.global_.memberships.models import CompetitionMembership
        from apps.global_.messages.services import _push
    except Exception:  # noqa: BLE001 - 推送依赖缺失时静默
        return
    payload = {
        'type': 'stock-updated',
        'round': int(round_no or 0),
        'serverTime': timezone.now().isoformat(),
    }
    try:
        user_ids = list(
            CompetitionMembership.objects
            .filter(competition_id=competition_id, is_active=True)
            .values_list('user_id', flat=True)
        )
    except Exception:  # noqa: BLE001
        return
    for uid in user_ids:
        try:
            _push(uid, dict(payload))
        except Exception:  # noqa: BLE001 - 单个推送失败静默（§4.3）
            pass


# ================================================================ 序列化（纯函数）


def _iso(dt) -> "str | None":
    return dt.isoformat() if dt else None


def serialize_stock_thin(stock, change_pct=0.0) -> dict:
    """股票**薄字段**（§4.1 列表 / §4.2 stocks 集合）。

    字段（§4.1）：code / name / currentPrice / initPrice / round / updatedAt / 涨跌幅；
    另附 id（§5.2 客户端 Map by code/id 幂等覆盖需要稳定键）。
    """
    return {
        'id': stock.id,
        'code': stock.code,
        'name': stock.name,
        'currentPrice': stock.current_price,
        'initPrice': stock.init_price,
        'round': stock.round,
        'changePct': change_pct or 0.0,
        'updatedAt': _iso(getattr(stock, 'updated_at', None)),
    }


def serialize_stock_detail(stock, *, field_map=None, pb_map=None, candle=None) -> dict:
    """股票详情（§4.1 /stock/stocks/{code}：含指标全字段）。

    字段与旧系统 _serialize_stock 对齐：有效碳排/幸福度/行业碳排均值/有效 PE/涨跌幅。
    """
    from .engine import (
        effective_carbon,
        effective_happiness,
        effective_industry_avg_carbon,
    )

    fm = field_map or {}
    pb = pb_map.get(stock.id, stock.industry_pe) if pb_map else stock.industry_pe

    change_pct = 0
    change_price = 0
    volume = 0
    if candle is not None:
        change_pct = float(candle.change_pct) if candle.change_pct else 0
        change_price = float(round2_like(float(candle.close) - float(candle.open)))
        volume = float(candle.volume) if getattr(candle, 'volume', None) else 0

    return {
        'id': stock.id,
        'code': stock.code,
        'name': stock.name,
        'totalShares': stock.total_shares,
        'initNetProfit': stock.init_net_profit,
        'industryPE': stock.industry_pe,
        'currentCarbon': stock.current_carbon,
        'industryAvgCarbon': stock.industry_avg_carbon,
        'happiness': stock.happiness,
        'carbonFieldRef': stock.carbon_field_ref,
        'happinessFieldRef': stock.happiness_field_ref,
        'industryAvgCarbonRefs': stock.industry_avg_carbon_refs,
        'pbCompanyId': stock.pb_company_id,
        'pbFieldId': stock.pb_field_id,
        'pbRandom': stock.pb_random,
        'companyId': stock.company_id,
        'initPrice': stock.init_price,
        'currentPrice': stock.current_price,
        'round': stock.round,
        'createdAt': _iso(getattr(stock, 'created_at', None)),
        'updatedAt': _iso(getattr(stock, 'updated_at', None)),
        'effectiveCurrentCarbon': effective_carbon(stock, fm),
        'effectiveHappiness': effective_happiness(stock, fm),
        'effectiveIndustryAvgCarbon': effective_industry_avg_carbon(stock, fm),
        'effectivePb': pb,
        'pbMode': 'linked' if (stock.pb_company_id and stock.pb_field_id) else 'random',
        'changePct': change_pct,
        'changePrice': change_price,
        'volume': volume,
    }


def round2_like(v) -> Decimal:
    """两位小数（复用 engine.round2 的大数安全实现，服务层轻量转口）。"""
    from .engine import round2

    return round2(v)


def serialize_candle(candle, *, stock_code: "str | None" = None) -> dict:
    """K 线（§4.1 candles / §4.2 candles 集合，薄字段）。"""
    return {
        'id': candle.id,
        'stockCode': stock_code if stock_code is not None else getattr(candle, 'stock_code', None),
        'round': candle.round,
        'open': candle.open,
        'high': candle.high,
        'low': candle.low,
        'close': candle.close,
        'changePct': candle.change_pct,
        'volume': candle.volume,
        'updatedAt': _iso(getattr(candle, 'updated_at', None)),
    }


def serialize_order(order, *, stock_code: "str | None" = None) -> dict:
    """委托（§4.1 /stock/orders、§4.2 orders 集合：我的订单变更）。"""
    return {
        'id': order.id,
        'stockId': order.stock_id,
        'stockCode': stock_code if stock_code is not None else getattr(order, 'stock_code', None),
        'fundsAccountId': order.funds_account_id,
        'side': order.side,
        'price': order.price,
        'quantity': order.quantity,
        'amount': order.amount,
        'status': order.status,
        'round': order.round,
        'createdAt': _iso(getattr(order, 'created_at', None)),
        'updatedAt': _iso(getattr(order, 'updated_at', None)),
    }


def serialize_holding(
    holding, *, stock_code: "str | None" = None, stock_name: "str | None" = None,
    current_price=None,
) -> dict:
    """持仓（§4.1 /stock/book、§4.2 holdings 集合：我的持仓变更）。"""
    market_value = None
    if current_price is not None:
        market_value = round2_like(Decimal(str(holding.shares)) * Decimal(str(current_price)))
    return {
        'id': holding.id,
        'fundsAccountId': holding.funds_account_id,
        'stockId': holding.stock_id,
        'stockCode': stock_code if stock_code is not None else getattr(holding, 'stock_code', None),
        'stockName': stock_name if stock_name is not None else getattr(holding, 'stock_name', None),
        'currentPrice': current_price,
        'shares': holding.shares,
        'costPrice': holding.cost_price,
        'marketValue': market_value,
        'updatedAt': _iso(getattr(holding, 'updated_at', None)),
    }


def serialize_account(account, *, field_balance=None) -> dict:
    """资金账户（§4.1 /stock/book、§4.2 accounts 集合：我的资金账户变更）。

    fieldBalance：绑定产业字段的实时现金（旧系统 _serialize_account(with_field_balance) 语义）。
    """
    return {
        'id': account.id,
        'name': account.name,
        'ownerType': account.owner_type,
        'companyId': account.company_id,
        'userId': account.user_id,
        'cashBalance': account.cash_balance,
        'bindFieldId': account.bind_field_id,
        'fieldBalance': field_balance,
        'createdAt': _iso(getattr(account, 'created_at', None)),
        'updatedAt': _iso(getattr(account, 'updated_at', None)),
    }


# ================================================================ 同步协议（§4.2，纯函数）


def parse_sync_since(raw) -> "object | None":
    """游标解析：ISO 时间字符串 → datetime；空/非法 → None（回退 snapshot，§4.2 失败恢复）。"""
    if not raw:
        return None
    return parse_datetime(str(raw).strip()) or None


def sync_mode(since) -> str:
    """since 为空 → snapshot（全量薄字段）；带 since → delta（§4.2）。"""
    return 'snapshot' if since is None else 'delta'


def parse_sync_limit(raw, default: int = SYNC_DEFAULT_LIMIT) -> int:
    """limit 解析：默认 500，钳制到 [1, SYNC_MAX_LIMIT]。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(SYNC_MAX_LIMIT, value))


def clip_sync_rows(rows: list, limit: int) -> tuple[list, bool]:
    """keyset 截断：取前 limit 条，超出置 hasMore（§4.2「limit 截断置 hasMore」）。"""
    rows = list(rows)
    return rows[:limit], len(rows) > limit


def resolve_sync_server_time(*, now, truncated_boundaries, has_more) -> str:
    """同步游标（修复续拉漏行）：

    - 无截断：游标 = 响应时刻；
    - **有截断**：游标 = 已交付行的 keyset 边界（各截断集合取最小值）再回拨 1µs——
      保证未交付的尾部行（updated_at ≤ 响应时刻）在续拉时能被取到；
      回拨造成的边界行重复投递由客户端按 id 幂等合并吸收（前端 useStockSync 已按此实现）。
    """
    if not has_more:
        return now.isoformat()
    boundaries = [b for b in (truncated_boundaries or []) if b is not None]
    if not boundaries:
        return now.isoformat()
    return (min(boundaries) - timedelta(microseconds=1)).isoformat()


def build_sync_envelope(
    *, mode: str, server_time: str, round_: int, has_more: bool,
    stocks: list, candles: list, orders: list, holdings: list, accounts: list,
) -> dict:
    """同步响应信封（§4.2 全字段语义：mode/serverTime/round/hasMore + 五集合）。"""
    return {
        'mode': mode,
        'serverTime': server_time,   # 下次游标（永远用上一响应的 serverTime，§4.2）
        'round': round_,
        'hasMore': has_more,
        'stocks': stocks,
        'candles': candles,
        'orders': orders,
        'holdings': holdings,
        'accounts': accounts,
    }


# ================================================================ 可见性裁剪（§4.2）


def owner_account_q(user, competition_id=None):
    """owner 可见性（§4.2）：accounts/orders/holdings 只回**我的**——
    USER 账户=本人，COMPANY 账户=**可查看**的所辖/本队公司
    （apps.common.authority.user_company_ids 判定：本公司队长与队员都能看）。

    注意这是**读**口径；下单/撤单用 ``user_operable_company_ids``（仅队长）。
    返回 (Q, is_all)。
    """
    from django.db.models import Q

    from apps.common.authority import user_company_ids

    ids = user_company_ids(user, competition_id)
    if '*' in ids:
        return Q(), True
    q = Q(owner_type='USER', user_id=getattr(user, 'id', None))
    if ids:
        q = q | Q(owner_type='COMPANY', company_id__in=sorted(ids))
    return q, False


def account_owned_by_user(account, user, company_ids) -> bool:
    """单账户归属判定（下单/撤单/读我的委托复用；纯函数，可单测）。

    - USER 账户：user_id == 本人（'*' 超管口径放行，同旧 _is_high_manager）；
    - COMPANY 账户：company_id ∈ 传入的公司集合（'*' = 全部）——读传「可查看」集合、
      写（下单/撤单）传「可操作」集合（``user_operable_company_ids``，仅队长）；
    - 未知 owner_type 恒拒绝（防御性）。
    """
    if account.owner_type == 'USER':
        return '*' in company_ids or account.user_id == getattr(user, 'id', None)
    if account.owner_type == 'COMPANY':
        if '*' in company_ids:
            return True
        try:
            return int(account.company_id or 0) in {int(c) for c in company_ids}
        except (TypeError, ValueError):
            return False
    return False


# ================================================================ 同步组装（含查询）


def build_last_candle_map(stock_ids) -> dict:
    """批量获取每只股票的最后一根 K 线（涨跌幅用），返回 {stock_id: candle}。

    语义来源：旧 views._build_candle_map（P0-#7 消除前端逐个请求 K 线的 N+1）。
    实现要点（性能）：PostgreSQL ``DISTINCT ON`` 单次索引扫描走 unique(stock, round)
    索引；原 Subquery 写法每股票执行一次子计划（500 股实测 ~200ms+），此版 ~5ms。
    不传股票时返回空映射。
    """
    from .models import StockCandle

    stock_ids = list(stock_ids or [])
    if not stock_ids:
        return {}
    last_candles = (
        StockCandle.objects.filter(stock_id__in=stock_ids)
        .order_by('stock_id', '-round')
        .distinct('stock_id')  # 每股取最新一根（DISTINCT ON 要求 order_by 前缀一致）
    )
    return {c.stock_id: c for c in last_candles}


def build_sync_payload(*, user, since_raw=None, limit_raw=None, competition_id=None) -> dict:
    """组装 §4.2 同步响应（snapshot / delta）。

    - snapshot（since 空）：全量薄字段，仍按 limit 分页；
    - delta（带 since）：各集合 ``updated_at > since``，``ORDER BY updated_at, id`` keyset
      （不用 OFFSET，§1 大表查询），limit 截断置 hasMore；
    - 可见性裁剪：orders/holdings/accounts 只返回我的（owner_account_q）；
    - serverTime 为响应时刻（下次游标）。
    """
    from django.db.models import Max

    from .models import Stock, StockCandle, StockFundsAccount, StockHolding, StockOrder

    since = parse_sync_since(since_raw)
    limit = parse_sync_limit(limit_raw)
    mode = sync_mode(since)

    def _keyset(qs):
        """§4.2 keyset：ORDER BY updated_at, id LIMIT n（不用 OFFSET）。"""
        return qs.order_by('updated_at', 'id')

    def _fetch(qs):
        rows, more = clip_sync_rows(list(_keyset(qs)[: limit + 1]), limit)
        # 截断时记录已交付行的 keyset 边界（最后一条 updated_at），供游标回拨
        boundary = rows[-1].updated_at if (more and rows) else None
        return rows, more, boundary

    owner_q, owner_all = owner_account_q(user, competition_id)
    visible_accounts = StockFundsAccount.objects.filter(owner_q)

    stocks_qs = Stock.objects.all()
    candles_qs = StockCandle.objects.select_related('stock')
    orders_qs = StockOrder.objects.select_related('stock').filter(funds_account__in=visible_accounts)
    holdings_qs = StockHolding.objects.select_related('stock').filter(funds_account__in=visible_accounts)
    accounts_qs = StockFundsAccount.objects.all() if owner_all else visible_accounts

    if since is not None:
        stocks_qs = stocks_qs.filter(updated_at__gt=since)
        candles_qs = candles_qs.filter(updated_at__gt=since)
        orders_qs = orders_qs.filter(updated_at__gt=since)
        holdings_qs = holdings_qs.filter(updated_at__gt=since)
        accounts_qs = accounts_qs.filter(updated_at__gt=since)

    stock_rows, more_s, b_s = _fetch(stocks_qs)
    candle_rows, more_c, b_c = _fetch(candles_qs)
    order_rows, more_o, b_o = _fetch(orders_qs)
    holding_rows, more_h, b_h = _fetch(holdings_qs)
    account_rows, more_a, b_a = _fetch(accounts_qs)
    has_more = bool(more_s or more_c or more_o or more_h or more_a)

    # 薄字段 + 涨跌幅（批量取最近一根 K 线，避免 N+1；旧 _build_candle_map 语义）
    candle_map = build_last_candle_map([s.id for s in stock_rows])
    stock_code_of = {s.id: s.code for s in stock_rows}

    stocks = [
        serialize_stock_thin(s, float(candle_map[s.id].change_pct) if s.id in candle_map else 0.0)
        for s in stock_rows
    ]
    candles = [
        serialize_candle(c, stock_code=stock_code_of.get(c.stock_id) or getattr(c.stock, 'code', None))
        for c in candle_rows
    ]
    orders = [
        serialize_order(o, stock_code=getattr(o.stock, 'code', None)) for o in order_rows
    ]
    holdings = [
        serialize_holding(
            h,
            stock_code=getattr(h.stock, 'code', None),
            stock_name=getattr(h.stock, 'name', None),
            current_price=getattr(h.stock, 'current_price', None),
        )
        for h in holding_rows
    ]
    accounts = [serialize_account(a) for a in account_rows]

    current_round = Stock.objects.aggregate(m=Max('round'))['m'] or 0
    return build_sync_envelope(
        mode=mode,
        server_time=resolve_sync_server_time(
            now=timezone.now(),
            truncated_boundaries=[b for more, b in (
                (more_s, b_s), (more_c, b_c), (more_o, b_o), (more_h, b_h), (more_a, b_a),
            ) if more],
            has_more=has_more,
        ),
        round_=current_round,
        has_more=has_more,
        stocks=stocks,
        candles=candles,
        orders=orders,
        holdings=holdings,
        accounts=accounts,
    )
