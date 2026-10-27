"""股票撮合 / 定价引擎（契约 §3；从旧系统 backend/apps/stock/engine.py 移植）。

纯函数（compute_match/compute_price/build_candle/compute_init_price）对齐原 engine.ts；
advance_round 是 ORM 编排入口。撮合=最高买 vs 最低卖，成交价须夹在 [卖价, 买价] 内
（全市场中点价会越出单笔限价）；未成交走平盘/趋势漂移但 round 照常推进，K 线无空洞。

多库适配（§3「适配点」）：competition_id 仅对外参数，ORM 不按比赛过滤（一个比赛一个库，
比赛归属即库归属）；事务一律 comp_atomic() 落比赛库连接；字段值走 field_key 口径
（IndustryField pk 解析）；推送只当信号（§4.3），轮次末尾广播一次 stock-updated。
"""
from __future__ import annotations

import importlib
import json
import logging
import math
import random
import threading
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation, localcontext
from typing import Any, Iterable

from django.db import connection, transaction

from apps.common.context import get_competition_alias

logger = logging.getLogger("gipfel")

EPS = Decimal("1e-9")


class StockError(Exception):
    """股票业务错误（契约 §3：旧 BusinessError 的本地替代，code/status 供视图层统一包装）。"""

    def __init__(self, message, code=400, status_code=None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code or code


def comp_atomic():
    """比赛库事务（契约 §3 适配点 2：多库下事务必须落比赛库连接）。"""
    return transaction.atomic(using=(get_competition_alias() or 'default'))


def round2(v) -> Decimal:
    """保留 2 位小数（Decimal 避免 float 累计误差）。

    必须在 localcontext(prec=70) 下 quantize：默认 context 28 位对 10^26 以上会
    InvalidOperation，曾被 except 吞成 0（现金清零事故）。
    """
    if isinstance(v, Decimal):
        d = v
    else:
        try:
            d = Decimal(str(v))
        except (ValueError, ArithmeticError, TypeError):
            return Decimal("0")
    with localcontext() as ctx:
        ctx.prec = 70
        try:
            return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return Decimal("0")


def clamp(v: float, lo: float, hi: float) -> float:
    """限幅辅助：把 v 截断到 [lo, hi]。"""
    return max(lo, min(hi, v))


def add_fluctuation(value: float, fluctuation_pct: float = 0.2) -> float:
    """给参数添加 ±fluctuation_pct 随机波动（模块级函数，避免每次调用重启定义）。"""
    return value * (1 + random.uniform(-fluctuation_pct, fluctuation_pct))


def candle_noise(seed_a: float, seed_b: float) -> float:
    """确定性伪随机（正弦哈希，可复现）：种子可为 Decimal/float/int，统一转 float。"""
    x = math.sin(float(seed_a) * 127.1 + float(seed_b) * 311.7) * 43758.5453
    return x - math.floor(x)


def compute_match(orders: Iterable[dict]) -> dict:
    """撮合预检：是否可成交 + 参考成交价（最高买与最低卖的中点）。

    注意：此处 tradePrice 只是参考价；逐笔撮合时每对成交价须夹到 [sell.price, buy.price]，
    否则会违反单方限价委托语义（见 advance_one_stock 的撮合循环）。
    """
    orders = list(orders)
    buys = [o for o in orders if o["side"] == "BUY"]
    sells = [o for o in orders if o["side"] == "SELL"]

    highest_buy = max((o["price"] for o in buys), default=0)
    lowest_sell = min((o["price"] for o in sells), default=0)

    total_buy_qty = sum(o["quantity"] for o in buys)
    total_sell_qty = sum(o["quantity"] for o in sells)
    total_buy_amount = sum(o["price"] * o["quantity"] for o in buys)
    total_sell_amount = sum(o["price"] * o["quantity"] for o in sells)

    matched = len(buys) > 0 and len(sells) > 0 and highest_buy >= lowest_sell
    trade_price = (highest_buy + lowest_sell) / 2 if matched else None

    return {
        "highestBuy": highest_buy,
        "lowestSell": lowest_sell,
        "totalBuyQty": total_buy_qty,
        "totalSellQty": total_sell_qty,
        "totalBuyAmount": total_buy_amount,
        "totalSellAmount": total_sell_amount,
        "matched": matched,
        "tradePrice": trade_price,
    }


def compute_pressure(buy_qty: float, sell_qty: float) -> float:
    """净买压力：∈ (-1, 1)，分母 +1 防除零。"""
    denom = buy_qty + sell_qty + 1
    return (buy_qty - sell_qty) / denom


def compute_carbon_drift(
    current_carbon: float,
    industry_avg_carbon: float,
    carbon_saturate_ratio: float = 2,
) -> float:
    """碳排趋势偏置（对数压缩）：碳排=均值→0、R 倍均值→-1、零碳排→+1；均值≤0 无法归一→0。"""
    if industry_avg_carbon <= 0:
        return 0
    if current_carbon <= 0:
        return 1
    r = current_carbon / industry_avg_carbon
    k = math.log(carbon_saturate_ratio if carbon_saturate_ratio > 1 else 2)
    return min(1, -math.log(r) / k)


def compute_drift(
    happiness: float,
    current_carbon: float,
    industry_avg_carbon: float,
    happiness_impact: float,
    carbon_impact: float,
    carbon_saturate_ratio: float = 2,
) -> float:
    """趋势偏置：幸福度/碳排压缩为长期趋势偏置。"""
    h = (happiness - 50) / 50
    c = compute_carbon_drift(current_carbon, industry_avg_carbon, carbon_saturate_ratio)
    return happiness_impact * h + carbon_impact * c


def compute_theoretical(
    last_close: float,
    pressure: float,
    drift: float,
    max_move_pct: float,
) -> float:
    """理论价：上轮收盘 × (1 + 压力×maxMovePct + 偏置×maxMovePct)。"""
    return last_close * (1 + pressure * max_move_pct + drift * max_move_pct)


def compute_price(factors: dict, config: dict) -> dict:
    """最终价：成交价与理论价加权后限幅，保留 2 位小数。"""
    pressure = compute_pressure(factors["buyQty"], factors["sellQty"])
    drift = compute_drift(
        factors["happiness"],
        factors["currentCarbon"],
        factors["industryAvgCarbon"],
        config["happinessImpact"],
        config["carbonImpact"],
        config["carbonSaturateRatio"],
    )
    theoretical = compute_theoretical(
        factors["lastClose"], pressure, drift, config["maxMovePct"]
    )

    # 非对称限幅（防连板 S10）：upper/lowerLimitPct 可分别覆盖涨跌侧，缺省回落 limitPct。
    upper_pct = config.get("upperLimitPct", config["limitPct"])
    lower_pct = config.get("lowerLimitPct", config["limitPct"])
    upper = factors["lastClose"] * (1 + upper_pct)
    lower = factors["lastClose"] * (1 - lower_pct)

    trade_price = factors.get("tradePrice")
    if factors["matched"] and trade_price is not None and math.isfinite(trade_price):
        w = config["tradePriceWeight"]
        blended = w * trade_price + (1 - w) * theoretical
        final = clamp(blended, lower, upper)
        used_trade_price = True
    else:
        final = clamp(factors["lastClose"], lower, upper)
        used_trade_price = False

    final = round2(final)
    return {
        "pressure": pressure,
        "drift": drift,
        "theoretical": theoretical,
        "final": final,
        "usedTradePrice": used_trade_price,
    }


def build_candle(
    open_: float,
    close: float,
    round_: int,
    theoretical: float | None = None,
    limit_pct: float = 0.1,
    upper_pct: float | None = None,
    lower_pct: float | None = None,
    trade_high: float | None = None,
    trade_low: float | None = None,
) -> dict:
    """构建 K 线（内部 float 运算，末尾 round2 到 0.01）。

    trade_high/trade_low 必须喂本轮真实成交价的极值：贴限价的成交会超出
    「body+理论价+噪声」的合成范围，K 线要如实反映（仍夹在限幅内）。
    """
    open_ = float(open_)
    close = float(close)

    up_pct = upper_pct if upper_pct is not None else limit_pct
    dn_pct = lower_pct if lower_pct is not None else limit_pct
    upper = float(round2(Decimal(str(open_)) * (Decimal("1") + Decimal(str(up_pct)))))
    lower = float(round2(Decimal(str(open_)) * (Decimal("1") - Decimal(str(dn_pct)))))
    range_ = upper - lower

    body_high = float(max(open_, close))
    body_low = float(min(open_, close))

    high = body_high
    low = body_low
    if theoretical is not None and math.isfinite(theoretical):
        t = float(min(max(theoretical, lower), upper))
        high = max(high, t)
        low = min(low, t)
    if trade_high is not None and math.isfinite(trade_high):
        high = max(high, float(min(max(trade_high, lower), upper)))
    if trade_low is not None and math.isfinite(trade_low):
        low = min(low, float(min(max(trade_low, lower), upper)))

    # 影线长度：优先真实成交价范围，其次理论价差，最后股价百分比。
    price = float(open_)
    if price > 0:
        if trade_high is not None and trade_low is not None:
            trade_range = float(trade_high) - float(trade_low)
            # 影线基础长度 = 成交价范围的30%~70%（确保影线能覆盖成交价）
            base_wick = trade_range * (0.3 + 0.4 * candle_noise(round_, open_))
        elif theoretical is not None and math.isfinite(theoretical):
            theory_diff = abs(float(theoretical) - close)
            base_wick = theory_diff * (0.5 + 0.5 * candle_noise(round_, open_))
        else:
            change_pct_abs = abs(close - open_) / price if price > 0 else 0
            base_wick_pct = 0.003 + min(0.007, change_pct_abs * 0.3)
            base_wick = price * base_wick_pct

        random_factor_a = 0.6 + 0.8 * candle_noise(round_, open_)
        random_factor_b = 0.6 + 0.8 * candle_noise(round_ * 3 + 7, open_)

        up_wick = base_wick * random_factor_a
        down_wick = base_wick * random_factor_b
    else:
        wick = range_ * 0.05  # 5%的涨跌停区间
        up_wick = wick * candle_noise(round_, open_)
        down_wick = wick * candle_noise(round_ * 3 + 7, open_)

    high = float(round2(min(upper, high + up_wick)))
    low = float(round2(max(lower, low - down_wick)))

    change_pct = (
        float(
            (Decimal(str(close - open_)) / Decimal(str(open_)) * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        if open_ != 0
        else 0
    )
    return {
        "round": round_,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "changePct": change_pct,
    }


def compute_init_price(
    init_net_profit: float, total_shares: float, industry_pe: float
) -> float:
    """初始价公式：ROUND(initNetProfit*10000/totalShares/industryPE, 2)。"""
    if industry_pe <= 0 or total_shares <= 0:
        # 非法参数不再静默返回 0：告警便于排查配置错误
        logger.warning(
            "compute_init_price 非法参数 industry_pe=%s total_shares=%s，返回 0",
            industry_pe,
            total_shares,
        )
        return 0
    price = (
        Decimal(str(init_net_profit))
        * 10000
        / Decimal(str(total_shares))
        / Decimal(str(industry_pe))
    )
    return float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


DEFAULT_STOCK_CONFIG: dict = {
    "limitPct": 0.1,
    "maxMovePct": 0.08,
    "happinessImpact": 0.3,
    "carbonImpact": 0.3,
    "mmDepthPct": 0.0005,
    "mmMinQty": 500,
    "mmMaxQty": 50000,
    "mmSpreadPct": 0.02,
    "mmSkewPct": 0.02,
    "interventionMode": "regression",
    "regressionPct": 0.02,
    "tradePriceWeight": 0.7,
    "carbonSaturateRatio": 2,
    # 做市商自成交配置
    "mmSelfTradeEnabled": True,
    "mmSelfTradePct": 0.005,
    "mmSelfTradeQtyPct": 0.05,
    # 做市商随机事件配置
    "mmBadNewsProb": 0.05,
    "mmGoodNewsProb": 0.04,
    "mmBadNewsImpact": 0.08,
    "mmGoodNewsImpact": 0.06,
    # 估值回归配置
    "mmRegressionThreshold": 0.3,
    "mmRegressionStrength": 0.2,
    # 市场自然波动配置
    "mmCallbackEnabled": True,
}

# 防连板因子：上轮封板时本轮同侧限幅收紧。默认 10%×0.96=9.6% < 9.9%（封板判定线）。
_ANTI_STREAK_FACTOR = 0.96
# 绝对上限与判板线挂钩：limitPct 大时 96% 收缩仍可能 ≥9.9%（15%×0.96=14.4%），
# 故同侧取 min(limitPct×0.96, 9.6%)，任意配置下连板都不可能。
_ANTI_STREAK_CAP_PCT = 0.096


def resolve_stock_config(input_: dict | None) -> dict:
    """将未知/缺失字段合并回默认值，保证运行期类型完整。"""
    if not input_ or not isinstance(input_, dict):
        return dict(DEFAULT_STOCK_CONFIG)
    merged = dict(DEFAULT_STOCK_CONFIG)
    merged.update(input_)
    return merged


def _parse_exact_number(text) -> "int | Decimal | None":
    """数字字符串 → int（任意精度）或 Decimal；解析失败 None。

    绝不 float 化：double 在 2^53 以上丢精度，且 JSON 出站变 2e+30 科学计数，
    前端正则不识别导致「大数不展示」。
    """
    s = str(text).strip() if text is not None else ""
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


_field_key_cache: dict[int, "str | None"] = {}


def _field_key_of(industry_field_id) -> "str | None":
    """产业字段 ID（IndustryField pk，pb_field_id/bind_field_id 口径）→ field_key。

    旧系统按 (company_id, industry_field_id) 存取，新系统 CompanyFieldValue 按
    (company, field_key, fiscal_year) 存取（§3 适配点 4）。
    """
    try:
        fid = int(industry_field_id)
    except (TypeError, ValueError):
        return None
    if fid in _field_key_cache:
        return _field_key_cache[fid]
    from apps.competition.industries.models import IndustryField

    key = IndustryField.objects.filter(pk=fid).values_list("field_key", flat=True).first()
    _field_key_cache[fid] = key
    return key


def resolve_field_value_or_default(
    company_id: int, industry_field_id: int
) -> "int | Decimal | None":
    """读取公司产业字段当前值，无记录回退 IndustryField.default_value。

    返回 int|Decimal|None（不 float 化）；调用方与 float 混算会 TypeError，需 Decimal(str(v))。
    """
    from apps.competition.industries.models import CompanyFieldValue, IndustryField

    field_key = _field_key_of(industry_field_id)
    if not field_key:
        return None
    fv = CompanyFieldValue.objects.filter(
        company_id=company_id, field_key=field_key, fiscal_year__isnull=True
    ).first()
    if fv is not None and fv.value is not None:
        n = _parse_exact_number(fv.value)
        if n is not None:
            return n
    try:
        field = IndustryField.objects.get(pk=industry_field_id)
    except IndustryField.DoesNotExist:
        return None
    if field.default_value is not None:
        n = _parse_exact_number(field.default_value)
        if n is not None:
            return n
    return None


# 区域总览数据源候选（旧 apps.regions.views._get_map_overview）。MapRegion 已改为
# MapNode/MapEdge，旧「区域总览卡片」不存在时 cards 为空；找不到入口回退空映射
# （effective_* 随即回落 stock 静态值）。
_MAP_OVERVIEW_SOURCES = (
    "apps.competition.basedata.services.get_map_overview",
    "apps.competition.basedata.views.get_map_overview",
)


def _load_map_overview(competition_id: int) -> list:
    """解析区域总览数据源（可插拔），不可用返回 []。"""
    for dotted in _MAP_OVERVIEW_SOURCES:
        module_path, _, name = dotted.rpartition(".")
        try:
            fn = getattr(importlib.import_module(module_path), name, None)
        except Exception:  # noqa: BLE001 - 数据源不可用按旧逻辑回退
            continue
        if callable(fn):
            try:
                return fn(competition_id) or []
            except Exception:  # noqa: BLE001
                logger.warning("resolve_field_value_map 数据源失败 %s", dotted, exc_info=True)
                return []
    return []


def resolve_field_value_map(competition_id: int) -> dict[str, float | None]:
    """构建「区域:卡片 → 实时值」映射，供股票绑定字段实时引用（数据源见 _MAP_OVERVIEW_SOURCES）。"""
    field_map: dict[str, float | None] = {}
    if not competition_id:
        return field_map
    try:
        overview = _load_map_overview(competition_id)
    except Exception:  # noqa: BLE001 - 区域服务不可用时回退空映射
        logger.warning("resolve_field_value_map 失败 comp=%s", competition_id, exc_info=True)
        return field_map
    for r in overview:
        for card in r.get("cards", []):
            key = f"{r.get('region')}:{card.get('id')}"
            val: float | None = None
            if card.get("valid") and card.get("value") is not None:
                try:
                    n = float(card["value"])
                    val = n if math.isfinite(n) else None
                except (ValueError, TypeError):
                    val = None
            field_map[key] = val
    return field_map


def _parse_field_ref(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
        region = v.get("region") if isinstance(v, dict) else None
        card_id = v.get("cardId") if isinstance(v, dict) else None
        if isinstance(region, str) and (isinstance(card_id, str) or isinstance(card_id, int)):
            return {"region": region, "cardId": str(card_id)}
    except (ValueError, TypeError):
        pass
    return None


def _parse_field_refs(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if not isinstance(v, list):
            return []
        result = []
        for x in v:
            if not isinstance(x, dict):
                continue
            region = x.get("region")
            card_id = x.get("cardId")
            if isinstance(region, str) and (isinstance(card_id, str) or isinstance(card_id, int)):
                result.append({"region": region, "cardId": str(card_id)})
        return result
    except (ValueError, TypeError):
        return []


def effective_carbon(stock, field_map: dict) -> float:
    ref = _parse_field_ref(getattr(stock, "carbon_field_ref", None))
    if ref:
        v = field_map.get(f"{ref['region']}:{ref['cardId']}")
        if isinstance(v, (int, float)):
            return v
    return stock.current_carbon


def effective_happiness(stock, field_map: dict) -> float:
    ref = _parse_field_ref(getattr(stock, "happiness_field_ref", None))
    if ref:
        v = field_map.get(f"{ref['region']}:{ref['cardId']}")
        if isinstance(v, (int, float)):
            return v
    return stock.happiness


def effective_industry_avg_carbon(stock, field_map: dict) -> float:
    refs = _parse_field_refs(getattr(stock, "industry_avg_carbon_refs", None))
    vals: list[float] = []
    for ref in refs:
        v = field_map.get(f"{ref['region']}:{ref['cardId']}")
        if isinstance(v, (int, float)):
            vals.append(v)
    if vals:
        avg = sum(vals) / len(vals)
        return round(avg * 100) / 100
    return stock.industry_avg_carbon


def random_pb() -> float:
    """生成一个 0~20 的随机 PE（保留两位小数）。"""
    return round(random.random() * 20 * 100) / 100


def clamp_pb(v: float) -> float:
    """将 PE 值钳制到 [0, 20] 并保留两位小数。"""
    if not math.isfinite(v):
        # 非有限值（配置/上游异常）不再静默随机，改为告警后回退随机 PE 便于排查
        logger.warning("clamp_pb 收到非有限值 %s，回退随机 PE", v)
        return random_pb()
    c = min(20, max(0, v))
    return round2(c)


def resolve_effective_pbs(stocks: list) -> dict[int, float]:
    """批量计算股票的有效 PE：字段值 → 字段默认值 → industry_pe 逐级回退。

    非法值仍按旧行为静默 fallback（避免拖崩列表渲染），但逐条 logger.warning 留据，
    便于排查「PE 与公司字段值对不上」。
    """
    result: dict[int, float] = {}
    linked = [s for s in stocks if getattr(s, "pb_company_id", None) and getattr(s, "pb_field_id", None)]
    if linked:
        from apps.competition.industries.models import CompanyFieldValue, IndustryField

        company_ids = list({s.pb_company_id for s in linked})
        field_ids = list({s.pb_field_id for s in linked})
        key_of = {fid: _field_key_of(fid) for fid in field_ids}
        field_keys = [k for k in key_of.values() if k]
        val_map: dict[tuple[int, str], float] = {}
        for fv in CompanyFieldValue.objects.filter(
            company_id__in=company_ids, field_key__in=field_keys, fiscal_year__isnull=True
        ):
            if fv.value is None:
                continue
            try:
                n = float(fv.value)
                if math.isfinite(n):
                    val_map[(fv.company_id, fv.field_key)] = n
                else:
                    logger.warning(
                        "resolve_effective_pbs: 非有限值 company_id=%s field_key=%s value=%r，回退到 industry_pe",
                        fv.company_id, fv.field_key, fv.value,
                    )
            except (ValueError, TypeError):
                logger.warning(
                    "resolve_effective_pbs: value 无法解析为浮点 company_id=%s field_key=%s value=%r",
                    fv.company_id, fv.field_key, fv.value,
                )
        default_map: dict[str, float] = {}
        for f in IndustryField.objects.filter(pk__in=field_ids):
            if f.default_value is None:
                continue
            try:
                n = float(f.default_value)
                if math.isfinite(n):
                    default_map[f.field_key] = n
                else:
                    logger.warning(
                        "resolve_effective_pbs: IndustryField 非有限默认值 field_id=%s default_value=%r",
                        f.id, f.default_value,
                    )
            except (ValueError, TypeError):
                logger.warning(
                    "resolve_effective_pbs: IndustryField default 无法解析 field_id=%s default_value=%r",
                    f.id, f.default_value,
                )
        for s in linked:
            key = key_of.get(s.pb_field_id)
            v = val_map.get((s.pb_company_id, key)) if key else None
            if v is None and key:
                v = default_map.get(key)
            result[s.id] = v if v is not None else s.industry_pe
    for s in stocks:
        if s.id not in result:
            result[s.id] = s.industry_pe
    return result


def apply_pb_round(stock, pb_value_map: dict | None = None) -> None:
    """推进一轮时更新 PE，并据最新有效 PE 实时重算初始价。

    pb_value_map 由 _build_pb_value_map 批量构建；不传则逐股查库（原实现的 N+1 查询）。
    """
    pb_company_id = getattr(stock, "pb_company_id", None)
    pb_field_id = getattr(stock, "pb_field_id", None)
    pb_random = getattr(stock, "pb_random", None)
    if pb_company_id and pb_field_id:
        if pb_value_map is not None:
            v = pb_value_map.get((pb_company_id, pb_field_id))
        else:
            v = resolve_field_value_or_default(pb_company_id, pb_field_id)
        industry_pe = v if (v is not None and v > 0) else stock.industry_pe
        new_pb_random = None
    else:
        prev = pb_random if pb_random is not None else random_pb()
        step = random.random() * 4 - 2  # [-2, 2]
        nxt = clamp_pb(prev + step)
        industry_pe = nxt
        new_pb_random = nxt
    init_price = compute_init_price(stock.init_net_profit, stock.total_shares, industry_pe)
    stock.industry_pe = industry_pe
    stock.init_price = init_price
    if new_pb_random != pb_random:
        stock.pb_random = new_pb_random
    stock.save(update_fields=["industry_pe", "init_price", "pb_random"])


def _build_pb_value_map(stocks: list) -> dict[tuple[int, int], float | None]:
    """批量构建 {(company_id, field_id): 有效PE值}（联动模式用），消除 N+1 查库（H4）。

    口径同 resolve_field_value_or_default；内部按 field_key 查，键仍为
    (company_id, pb_field_id) 供调用方原样使用。
    """
    linked = [s for s in stocks if getattr(s, "pb_company_id", None) and getattr(s, "pb_field_id", None)]
    result: dict[tuple[int, int], float | None] = {}
    if not linked:
        return result
    from apps.competition.industries.models import CompanyFieldValue, IndustryField

    company_ids = list({s.pb_company_id for s in linked})
    field_ids = list({s.pb_field_id for s in linked})
    key_of = {fid: _field_key_of(fid) for fid in field_ids}
    field_keys = [k for k in key_of.values() if k]
    val_map: dict[tuple[int, str], float] = {}
    for fv in CompanyFieldValue.objects.filter(
        company_id__in=company_ids, field_key__in=field_keys, fiscal_year__isnull=True
    ):
        try:
            n = float(fv.value) if fv.value is not None else float("nan")
            if math.isfinite(n):
                val_map[(fv.company_id, fv.field_key)] = n
        except (ValueError, TypeError):
            pass
    default_map: dict[str, float] = {}
    for f in IndustryField.objects.filter(pk__in=field_ids):
        if f.default_value is not None:
            try:
                n = float(f.default_value)
                if math.isfinite(n):
                    default_map[f.field_key] = n
            except (ValueError, TypeError):
                pass
    for s in linked:
        key = (s.pb_company_id, s.pb_field_id)
        field_key = key_of.get(s.pb_field_id)
        if field_key and (s.pb_company_id, field_key) in val_map:
            result[key] = val_map[(s.pb_company_id, field_key)]
        elif field_key and field_key in default_map:
            result[key] = default_map[field_key]
        else:
            result[key] = None
    return result


def write_field_value_in_tx(
    company_id: int, industry_field_id: int, value: str
) -> None:
    """事务内写入单个字段值（version 乐观锁 + 冲突重试一次，同旧 _write_field_value）。"""
    from apps.competition.industries.models import CompanyFieldValue

    field_key = _field_key_of(industry_field_id)
    if not field_key:
        logger.warning(
            "[stock] write_field_value_in_tx 字段不存在 industry_field_id=%s", industry_field_id,
        )
        return
    fv = CompanyFieldValue.objects.filter(
        company_id=company_id, field_key=field_key, fiscal_year__isnull=True
    ).first()
    if fv is None:
        CompanyFieldValue.objects.create(
            company_id=company_id,
            field_key=field_key,
            fiscal_year=None,
            value=value,
            version=1,
        )
        return
    # 乐观锁：WHERE 含 version，避免并发写入被静默覆盖、version 写歪导致后续编辑永久 409。
    updated = CompanyFieldValue.objects.filter(
        pk=fv.pk, version=fv.version
    ).update(value=value, version=fv.version + 1)
    if not updated:
        # 版本冲突：重读最新版本后重试一次（并发写入优先）。
        fv = CompanyFieldValue.objects.filter(
            company_id=company_id, field_key=field_key, fiscal_year__isnull=True
        ).first()
        if fv is not None:
            updated = CompanyFieldValue.objects.filter(
                pk=fv.pk, version=fv.version
            ).update(value=value, version=fv.version + 1)
        if not updated:
            # 极端情况下仍冲突：记录告警并跳过本次写入，避免静默覆盖也不阻断整轮推进
            logger.warning(
                "[stock] write_field_value_in_tx 乐观锁冲突重试失败 company=%s field=%s",
                company_id, field_key,
            )


def _recompute_calc_after_cash_write(company_ids) -> None:
    """结算写入绑定字段后重算这些公司的计算字段（失败不拖垮整轮结算）。

    必须逐家公司套独立保存点：重算异常后若不加保存点，当前事务已被标记「需回滚」，
    后续任何查询都会抛 TransactionManagementError。
    """
    from apps.competition.companies.models import Company
    from apps.competition.industries.services import recompute_company_fields

    for cid in company_ids:
        try:
            company = Company.objects.filter(pk=cid).first()
            if company is None:
                continue
            with comp_atomic():
                recompute_company_fields(company)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[stock] 结算后重算公司 #%s 计算字段失败：%s", cid, exc
            )


def calculate_raw_fundamental_score(stock) -> float:
    """原始基本面评分（0-100，越高越好），用于相对排名：PE/碳排/幸福度/股本四因子。"""
    score = 50.0

    pe = getattr(stock, 'industry_pe', None)
    if pe and pe > 0:
        pe_float = float(pe)
        if pe_float <= 10:
            score += 20
        elif pe_float <= 15:
            score += 10
        elif pe_float <= 20:
            score += 0
        else:
            score -= 10

    carbon = getattr(stock, 'current_carbon', None)
    avg_carbon = getattr(stock, 'industry_avg_carbon', None)
    if carbon is not None and avg_carbon and avg_carbon > 0:
        carbon_float = float(carbon)
        avg_carbon_float = float(avg_carbon)
        carbon_ratio = carbon_float / avg_carbon_float
        if carbon_ratio < 0.7:
            score += 15
        elif carbon_ratio < 0.9:
            score += 5
        elif carbon_ratio > 1.3:
            score -= 15
        elif carbon_ratio > 1.1:
            score -= 5

    happiness = getattr(stock, 'happiness', None)
    if happiness is not None:
        happiness_float = float(happiness)
        if happiness_float >= 80:
            score += 15
        elif happiness_float >= 60:
            score += 5
        elif happiness_float < 40:
            score -= 10

    total_shares = getattr(stock, 'total_shares', None)
    if total_shares and total_shares > 0:
        shares_billion = float(total_shares) / 10000
        if 2 <= shares_billion <= 8:
            score += 10
        elif shares_billion < 1:
            score -= 5
        elif shares_billion > 15:
            score -= 5

    return clamp(score, 0, 100)


def calculate_relative_fundamental_score(stock, all_stocks: list) -> float:
    """基于相对排名的基本面评分（-0.5~0.5）：横向比较避免同涨同跌，仅前 30% 得正分。"""
    if not all_stocks or len(all_stocks) <= 2:
        raw_score = calculate_raw_fundamental_score(stock)
        return clamp((raw_score - 50) / 100.0, -0.3, 0.3)

    raw_scores = []
    for s in all_stocks:
        raw_scores.append(calculate_raw_fundamental_score(s))

    current_score = calculate_raw_fundamental_score(stock)
    rank = sum(1 for s in raw_scores if s < current_score)
    # (rank + 0.5) / len：避免所有股票基本面相同时全部得最低分
    percentile = (rank + 0.5) / len(raw_scores)

    if percentile >= 0.7:
        score = (percentile - 0.7) * 1.67
    elif percentile <= 0.3:
        score = (percentile - 0.3) * 1.67
    else:
        score = 0.0

    random_factor = random.uniform(-0.1, 0.1)
    score += random_factor

    return clamp(score, -0.5, 0.5)


def calculate_fundamental_score(stock, all_stocks: list | None = None) -> float:
    """基本面评分：≤2 只股票用绝对评分（避免极端分化），否则用相对排名（实现市场分化）。"""
    if not all_stocks or len(all_stocks) <= 2:
        raw_score = calculate_raw_fundamental_score(stock)
        # 0-100 → -0.3~0.3，缩小范围避免极端
        return clamp((raw_score - 50) / 100.0, -0.3, 0.3)
    else:
        return calculate_relative_fundamental_score(stock, all_stocks)


def generate_market_maker_orders(
    stock,
    competition_id: int,
    stock_config: dict,
    mm_override: dict | None = None,
    consecutive_up: int = 0,
    consecutive_down: int = 0,
    last_change: float = 0.0,
    field_map: dict | None = None,
    all_stocks: list | None = None,
) -> tuple[int, bool]:
    """AI 做市商：为指定股票生成买卖挂单，返回 (生成订单数, 是否干预)。

    报价中心 = 基本面/相对排名评分 + 反向动量偏置（涨→下移、跌→上移，抑制追涨杀跌）；
    再叠加波动自适应价差（封顶 2 倍）、连续封板回归锚干预与自成交。
    """
    from .models import StockFundsAccount, StockHolding, StockOrder

    enabled = (mm_override or {}).get("enabled", True)
    if not enabled:
        return 0, False

    # 用户交易越活跃，做市商干预越少
    mm_intensity = (mm_override or {}).get("intensity", 1.0)

    base_spread_pct = stock_config.get("mmSpreadPct", 0.02)
    base_levels = stock_config.get("mmLevels", 3)
    base_skew_pct = stock_config.get("mmSkewPct", 0.02)
    base_depth_pct = stock_config.get("mmDepthPct", 0.001)

    # 波动后 clamp 到 ±30%，防止多次叠加后偏离过大
    spread_pct = clamp(add_fluctuation(base_spread_pct, 0.15), base_spread_pct * 0.7, base_spread_pct * 1.3)
    levels = max(1, min(10, int(round(add_fluctuation(base_levels, 0.1)))))
    skew_pct = clamp(add_fluctuation(base_skew_pct, 0.2), base_skew_pct * 0.7, base_skew_pct * 1.3)
    depth_pct = clamp(add_fluctuation(base_depth_pct, 0.25), base_depth_pct * 0.7, base_depth_pct * 1.3)

    override_base = (mm_override or {}).get("baseQuantity")
    if override_base is not None:
        base_quantity = override_base
    else:
        calculated_quantity = int(round(Decimal(str(stock.total_shares or 0)) * 10000 * Decimal(str(depth_pct))))
        base_quantity = max(
            stock_config["mmMinQty"],
            min(
                stock_config["mmMaxQty"],
                int(round(add_fluctuation(float(calculated_quantity), 0.2))),  # 数量波动±20%
            ),
        )

    mm_self_trade_pct = add_fluctuation(stock_config.get("mmSelfTradePct", 0.005), 0.3)  # 偏移±30%
    mm_self_trade_qty_pct = add_fluctuation(stock_config.get("mmSelfTradeQtyPct", 0.1), 0.2)  # 数量±20%

    base_price = stock.current_price
    if base_price <= 0:
        return 0, False

    fundamental_score = calculate_fundamental_score(stock, all_stocks)

    # 波动自适应价差：|上轮涨跌| 越大价差越宽（封顶 2 倍）
    vol_scale = 1 + min(1.0, abs(last_change) / 10.0)
    spread_eff = spread_pct * vol_scale

    # 动量偏置：涨 → 报价下移，跌 → 上移（反向操作，抑制追涨杀跌）；封板时放大
    momentum_skew = clamp(last_change / 10.0, -1.0, 1.0) * skew_pct
    if consecutive_up >= 1 or consecutive_down >= 1:
        momentum_skew *= 1.5

    fundamental_skew = fundamental_score * skew_pct * 0.2

    # 估值回归偏置：价格偏离初始价过远时产生回归力量
    init_price = float(getattr(stock, 'init_price', 0))
    current_price_float = float(stock.current_price)
    if init_price > 0:
        price_deviation = (current_price_float - init_price) / init_price
        regression_threshold = stock_config.get("mmRegressionThreshold", 0.25)
        regression_strength = stock_config.get("mmRegressionStrength", 0.3)

        if abs(price_deviation) > regression_threshold:
            regression_skew = -price_deviation * skew_pct * regression_strength
        else:
            regression_skew = 0.0
    else:
        regression_skew = 0.0

    # 动量 60% / 基本面 20% / 估值回归 20%
    skew = momentum_skew * 0.6 + fundamental_skew * 0.2 + regression_skew * 0.2

    # 限制偏置范围，避免过度偏移
    skew = clamp(skew, -skew_pct * 1.2, skew_pct * 1.2)

    # 随机利空/利好事件（独立概率，不互斥）：模拟真实市场的不确定性
    bad_news_prob = stock_config.get("mmBadNewsProb", 0.03)
    good_news_prob = stock_config.get("mmGoodNewsProb", 0.02)
    bad_news_impact = stock_config.get("mmBadNewsImpact", 0.06)
    good_news_impact = stock_config.get("mmGoodNewsImpact", 0.04)

    if random.random() < bad_news_prob:
        impact = random.uniform(bad_news_impact * 0.3, bad_news_impact * 1.2)
        skew -= impact * skew_pct
        logger.info(f"[stock] 做市商利空事件: stock={stock.code}, impact={impact:.3f}")

    if random.random() < good_news_prob:
        impact = random.uniform(good_news_impact * 0.3, good_news_impact * 1.2)
        skew += impact * skew_pct
        logger.info(f"[stock] 做市商利好事件: stock={stock.code}, impact={impact:.3f}")

    # 做市商资金账户（比赛归属即库归属，无需 competition_id）
    mm_account, _ = StockFundsAccount.objects.get_or_create(
        name="AI做市商",
        defaults={"owner_type": "COMPANY", "cash_balance": 1_000_000_000},
    )

    current_round = stock.round

    # 只撤做市商旧轮订单：跨轮仍在价格范围内的旧单由 advance_one_stock 统一筛选保留
    StockOrder.objects.filter(
        stock_id=stock.id,
        status="PENDING",
        funds_account_id=mm_account.id,
        round__lt=current_round,
    ).update(status="CANCELLED")

    # 回归锚干预（连续封板 ≥ 3 轮）：挂大单对冲，量随连续轮数放大
    consec = max(consecutive_up, consecutive_down)
    need_intervene = (
        stock_config["interventionMode"] == "regression" and consec >= 3
    )
    intervention_qty = base_quantity * 2 * min(consec, 2) if need_intervene else 0

    total_sell_qty = sum(base_quantity * i for i in range(1, levels + 1))
    total_sell_qty += intervention_qty

    # 自成交：无人交易时主动制造价格波动
    self_trade_enabled = stock_config.get("mmSelfTradeEnabled", True)
    self_trade_pct = mm_self_trade_pct
    self_trade_qty_pct = mm_self_trade_qty_pct

    mm_holding = StockHolding.objects.filter(
        funds_account_id=mm_account.id, stock_id=stock.id
    ).first()
    current_shares = mm_holding.shares if mm_holding else 0
    need_shares = total_sell_qty - current_shares

    orders: list[StockOrder] = []

    if need_shares > 0:
        # 现金不足则按可用现金缩减建仓数量
        cost_per_share = round2(Decimal(str(base_price)))
        total_cost = cost_per_share * Decimal(str(need_shares))
        available_cash = Decimal(str(mm_account.cash_balance))
        if available_cash < total_cost and cost_per_share > 0:
            need_shares = int((available_cash / cost_per_share).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            total_sell_qty = min(total_sell_qty, Decimal(str(current_shares)) + Decimal(str(need_shares)))
        if need_shares > 0:
            if mm_holding is None:
                StockHolding.objects.create(
                    funds_account_id=mm_account.id,
                    stock_id=stock.id,
                    shares=round2(total_sell_qty),
                    cost_price=round2(base_price),
                )
            else:
                mm_holding.shares = Decimal(str(mm_holding.shares)) + Decimal(str(need_shares))
                mm_holding.save(update_fields=["shares"])
            actual_cost = round2(Decimal(str(base_price)) * Decimal(str(need_shares)))
            mm_account.cash_balance = Decimal(str(mm_account.cash_balance)) - actual_cost
            mm_account.save(update_fields=["cash_balance"])

    if need_intervene and mm_intensity > 0.3:  # 用户交易不活跃时才干预
        is_up = consecutive_up >= 2
        intervention_price = round2(
            base_price * (1 + (stock_config["regressionPct"] if is_up else -stock_config["regressionPct"]))
        )
        adjusted_intervention_qty = int(round(intervention_qty * mm_intensity))
        if adjusted_intervention_qty > 0:
            orders.append(StockOrder(
                stock_id=stock.id,
                funds_account_id=mm_account.id,
                side="SELL" if is_up else "BUY",
                price=intervention_price,
                quantity=adjusted_intervention_qty,
                amount=round2(intervention_price * adjusted_intervention_qty),
                status="PENDING",
                round=current_round,
            ))

    # 报价中心：按反向动量偏置整体平移（涨 → 下移，跌 → 上移）
    quote_center = round2(Decimal(str(base_price)) * (Decimal("1") - Decimal(str(skew))))
    # 防止 quote_center 极端值
    min_center = round2(base_price * Decimal("0.5"))
    max_center = round2(base_price * Decimal("2.0"))
    quote_center = max(min_center, min(max_center, quote_center))

    # 卖单不超可用持仓：跟踪做市商当前持仓
    mm_holding_refresh = StockHolding.objects.filter(
        funds_account_id=mm_account.id, stock_id=stock.id
    ).first()
    available_shares = Decimal(str(mm_holding_refresh.shares)) if mm_holding_refresh else Decimal("0")

    adjusted_base_quantity = int(round(base_quantity * mm_intensity))

    for i in range(1, levels + 1):
        offset = Decimal(str(spread_eff * i))
        sell_price = round2(quote_center * (Decimal("1") + offset))
        sell_qty = adjusted_base_quantity * i
        sell_amount = round2(sell_price * Decimal(str(sell_qty)))
        buy_price = round2(quote_center * (Decimal("1") - offset))
        if buy_price > 0:
            buy_qty_raw = (Decimal(str(sell_amount)) / Decimal(str(buy_price)))
            buy_qty = (buy_qty_raw * Decimal("1000000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / Decimal("1000000")
        else:
            buy_qty = Decimal("0")
        if buy_price > 0 and buy_qty > 0:
            orders.append(StockOrder(
                stock_id=stock.id,
                funds_account_id=mm_account.id,
                side="BUY",
                price=buy_price,
                quantity=buy_qty,
                amount=round2(Decimal(str(buy_price)) * buy_qty),
                status="PENDING",
                round=current_round,
            ))
        actual_sell_qty = min(Decimal(str(sell_qty)), available_shares)
        if actual_sell_qty > 0:
            orders.append(StockOrder(
                stock_id=stock.id,
                funds_account_id=mm_account.id,
                side="SELL",
                price=sell_price,
                quantity=actual_sell_qty,
                amount=round2(sell_price * actual_sell_qty),
                status="PENDING",
                round=current_round,
            ))
            available_shares -= actual_sell_qty

    # 自成交须在建仓之后（确保持仓已补充）
    if self_trade_enabled and not need_intervene and mm_intensity > 0.5:
        base_self_qty = max(1, int(round(base_quantity * self_trade_qty_pct * mm_intensity)))
        self_sell_qty = min(base_self_qty, int(available_shares))
        self_buy_qty = base_self_qty

        if last_change > 1.0:
            direction = -1 if random.random() < 0.7 else 1
        elif last_change < -1.0:
            direction = 1 if random.random() < 0.7 else -1
        else:
            direction = random.choice([-1, 1])

        price_offset_pct = self_trade_pct * min(2.0, abs(last_change) / 5.0 + 0.5)
        price_offset = direction * price_offset_pct

        self_trade_price = round2(Decimal(str(base_price)) * (Decimal("1") + Decimal(str(float(price_offset)))))
        st_buy_price = round2(self_trade_price * (Decimal("1") + Decimal("0.001")))
        st_sell_price = round2(self_trade_price * (Decimal("1") - Decimal("0.001")))

        if self_buy_qty > 0:
            orders.append(StockOrder(
                stock_id=stock.id,
                funds_account_id=mm_account.id,
                side="BUY",
                price=st_buy_price,
                quantity=self_buy_qty,
                amount=round2(st_buy_price * Decimal(str(self_buy_qty))),
                status="PENDING",
                round=current_round,
            ))

        if self_sell_qty > 0:
            orders.append(StockOrder(
                stock_id=stock.id,
                funds_account_id=mm_account.id,
                side="SELL",
                price=st_sell_price,
                quantity=self_sell_qty,
                amount=round2(st_sell_price * Decimal(str(self_sell_qty))),
                status="PENDING",
                round=current_round,
            ))
            available_shares -= Decimal(str(self_sell_qty))

    if orders:
        StockOrder.objects.bulk_create(orders)

        logger.info("[stock] 做市商参数自动生成: stock=%s, spread_pct=%.4f, levels=%s, "
                    "skew_pct=%.4f, depth_pct=%.6f, base_quantity=%s, "
                    "self_trade_pct=%.4f, self_trade_qty_pct=%.4f",
                    stock.code, spread_pct, levels, skew_pct, depth_pct,
                    base_quantity, mm_self_trade_pct, mm_self_trade_qty_pct)

    return len(orders), need_intervene


def _advance_round_flat(
    stock, competition_id: int, limit_pct: float,
    drift_data: dict | None = None,
) -> tuple[int, dict]:
    """平盘推进：轮次 +1、生成 K 线、作废旧轮订单（无订单/不成交两种情形共用）。

    保证各股票 round 全局同步、K 线无空洞；调用方须处于 comp_atomic() 内。
    drift_data 提供时按幸福度/碳排计算价格漂移，否则价格不动。
    """
    from .models import Stock, StockCandle, StockOrder
    from decimal import Decimal as D

    new_round = stock.round + 1
    old_price = stock.current_price

    # 无交易也按幸福度/碳排趋势漂移
    if drift_data:
        drift = compute_drift(
            drift_data["happiness"],
            drift_data["currentCarbon"],
            drift_data["industryAvgCarbon"],
            drift_data["happinessImpact"],
            drift_data["carbonImpact"],
            drift_data["carbonSaturateRatio"],
        )
        max_move = drift_data["maxMovePct"]
        # drift 定方向，幅度 ±60% 随机
        trend_drift = drift * (1 + random.uniform(-0.6, 0.6))
        # 基础噪声直接作用于价格（不乘 maxMovePct）：drift≈0 时也有波动
        base_noise_pct = random.uniform(-0.02, 0.02)
        theoretical = float(old_price) * (1 + trend_drift * max_move + base_noise_pct)
        upper = float(old_price) * (1 + limit_pct)
        lower = float(old_price) * (1 - limit_pct)
        new_price = round2(max(lower, min(upper, theoretical)))
        # 价格不为 0
        if new_price < Decimal("0.01"):
            new_price = Decimal("0.01")
    else:
        drift = 0.0
        new_price = old_price

    candle = build_candle(
        float(old_price), float(new_price), new_round, None, limit_pct
    )
    StockCandle.objects.create(
        stock_id=stock.id,
        open=candle["open"],
        high=candle["high"],
        low=candle["low"],
        close=candle["close"],
        change_pct=candle["changePct"],
        round=candle["round"],
    )
    Stock.objects.filter(pk=stock.id).update(
        current_price=new_price, round=new_round
    )
    # 轮次推进后处理旧轮订单：批量更新（避免逐个 save 的性能问题）
    old_orders = StockOrder.objects.filter(
        stock_id=stock.id,
        status="PENDING",
        round__lt=new_round,
    )

    if old_orders.exists():
        current_price = new_price
        upper_limit = current_price * (1 + D(str(limit_pct)))
        lower_limit = current_price * (1 - D(str(limit_pct)))

        cancel_ids = []
        keep_ids = []
        for order in old_orders:
            order_price = D(str(order.price))
            if order_price < lower_limit or order_price > upper_limit:
                cancel_ids.append(order.id)
            else:
                keep_ids.append(order.id)

        # 多库适配点 5：旧 emit_resource_changed 逐条广播改为 §4.3「推送只当信号」，轮末统一发
        if cancel_ids:
            StockOrder.objects.filter(id__in=cancel_ids).update(status="CANCELLED")

        if keep_ids:
            StockOrder.objects.filter(id__in=keep_ids).update(round=new_round)

    return new_round, candle


def advance_one_stock(
    stock,
    competition_id: int,
    field_map: dict,
    stock_config: dict,
    consecutive_up: int = 0,
    consecutive_down: int = 0,
    mm_config: dict | None = None,
    last_change: float = 0.0,
    all_stocks: list | None = None,
) -> dict | None:
    """推进单只股票一轮：撮合、定价、写持仓/现金/订单状态、生成 K 线。

    skipped=True 表示平盘轮（无成交，价格不动但 round 照常推进）；
    last_change 为上一根 K 线涨跌%（做市商反向偏置与波动自适应价差输入）。
    """
    from .models import Stock, StockCandle, StockFundsAccount, StockHolding, StockOrder

    with comp_atomic():
        # 本轮用户订单数（非做市商）：越少则做市商干预越强
        user_orders_count = StockOrder.objects.filter(
            stock_id=stock.id,
            round=stock.round,
            status="PENDING",
        ).exclude(funds_account__name="AI做市商").count()

        # 干预强度分档：0 单 1.0 / 1-2 单 0.7 / 3-5 单 0.4 / >5 单 0.1
        if user_orders_count == 0:
            mm_intensity = 1.0
        elif user_orders_count <= 2:
            mm_intensity = 0.7
        elif user_orders_count <= 5:
            mm_intensity = 0.4
        else:
            mm_intensity = 0.1

        mm_config_with_intensity = dict(mm_config or {})
        mm_config_with_intensity["intensity"] = mm_intensity

        # 做市商挂单（建仓/扣款/挂单与撮合同一事务）
        mm_count, mm_intervened = generate_market_maker_orders(
            stock, competition_id, stock_config, mm_config_with_intensity,
            consecutive_up, consecutive_down, last_change, field_map, all_stocks,
        )

        # 含旧轮 PENDING 单：价格仍在范围内的继续参与撮合
        all_orders = list(
            StockOrder.objects.select_related("funds_account").filter(
                stock_id=stock.id,
                status="PENDING",
                round__lte=stock.round,  # 包括当前轮和旧轮
            ).order_by("created_at")
        )

        from decimal import Decimal as D
        current_price = stock.current_price
        upper_limit = current_price * (1 + D(str(stock_config["limitPct"])))
        lower_limit = current_price * (1 - D(str(stock_config["limitPct"])))

        orders = []
        cancel_ids = []
        for order in all_orders:
            if order.round == stock.round:
                orders.append(order)
            else:
                order_price = D(str(order.price))
                if lower_limit <= order_price <= upper_limit:
                    orders.append(order)
                else:
                    cancel_ids.append(order.id)

        if cancel_ids:
            StockOrder.objects.filter(id__in=cancel_ids).update(status="CANCELLED")
        # 无任何订单（做市商关闭且无委托）→ 按幸福度/碳排趋势漂移，避免长期平盘
        if not orders:
            drift_data = {
                "happiness": float(effective_happiness(stock, field_map)),
                "currentCarbon": float(effective_carbon(stock, field_map)),
                "industryAvgCarbon": float(effective_industry_avg_carbon(stock, field_map)),
                "happinessImpact": stock_config["happinessImpact"],
                "carbonImpact": stock_config["carbonImpact"],
                "carbonSaturateRatio": stock_config["carbonSaturateRatio"],
                "maxMovePct": stock_config["maxMovePct"],
            }
            new_round, candle = _advance_round_flat(
                stock, competition_id, stock_config["limitPct"], drift_data
            )
            return {
                "stockId": stock.id,
                "code": stock.code,
                "round": new_round,
                "skipped": True,
                "matched": False,
                "finalPrice": float(candle["close"]),
                "pressure": 0.0,
                "drift": drift_data["happiness"] * stock_config["happinessImpact"],
                "theoretical": float(candle["close"]),
                "buyQty": 0,
                "sellQty": 0,
                "buyAmount": 0,
                "sellAmount": 0,
                "candle": candle,
            }

        match = compute_match(
            [{"side": o.side, "price": o.price, "quantity": o.quantity} for o in orders]
        )

        # expand-limit 模式：连续封板 ≥ 2 轮临时放宽限幅；但下方防连板硬约束会把同侧
        # 收紧到 9.6%，实际只在刻意配置更高封板判定时才有差异，保留兼容
        limit_pct = stock_config["limitPct"]
        if stock_config["interventionMode"] == "expand-limit":
            consec = max(consecutive_up, consecutive_down)
            if consec >= 2:
                limit_pct = min(0.2, stock_config["limitPct"] * (1 + 0.5 * (consec - 1)))
        cfg = dict(stock_config)
        cfg["limitPct"] = limit_pct

        # 防连板硬约束（S10）：上轮封板则本轮同侧限幅收紧到 min(96%, 9.6%)，
        # 单轮变动恒 < 9.9% 判板线 —— 任意挂单/任意 limitPct 下连板都不可能（两侧各自生效）。
        upper_pct = limit_pct
        lower_pct = limit_pct
        if consecutive_up >= 1:
            upper_pct = min(limit_pct * _ANTI_STREAK_FACTOR, _ANTI_STREAK_CAP_PCT)
        if consecutive_down >= 1:
            lower_pct = min(limit_pct * _ANTI_STREAK_FACTOR, _ANTI_STREAK_CAP_PCT)
        cfg["upperLimitPct"] = upper_pct
        cfg["lowerLimitPct"] = lower_pct

        # 数值入口统一转 float（compute_* 走 float），final 再转 Decimal 走 Decimal 化路径
        last_close_dec = Decimal(str(stock.current_price))
        factors_dec = {
            "lastClose": float(last_close_dec),
            "buyQty": float(match["totalBuyQty"]),
            "sellQty": float(match["totalSellQty"]),
            "matched": match["matched"],
            "tradePrice": (
                float(match["tradePrice"]) if match.get("tradePrice") is not None else None
            ),
            "happiness": float(effective_happiness(stock, field_map)),
            "currentCarbon": float(effective_carbon(stock, field_map)),
            "industryAvgCarbon": float(effective_industry_avg_carbon(stock, field_map)),
        }
        price = compute_price(factors_dec, cfg)

        # 市场自然波动：模拟真实市场的随机性与趋势性
        final_price = price["final"]

        callback_enabled = stock_config.get("mmCallbackEnabled", True)

        if callback_enabled:
            recent_candles = list(
                StockCandle.objects.filter(
                    stock_id=stock.id,
                ).order_by("-round")[:10]
            )

            if recent_candles:
                recent_changes = [float(c.change_pct) for c in recent_candles[:5]]
                avg_change = sum(recent_changes) / len(recent_changes)

                # 计算连续涨跌轮数（用局部变量，不覆盖外部传入的 consecutive_up/down）
                candle_consec_up = 0
                candle_consec_down = 0
                for candle in recent_candles:
                    if candle.change_pct > 0:
                        candle_consec_up += 1
                        candle_consec_down = 0
                    elif candle.change_pct < 0:
                        candle_consec_down += 1
                        candle_consec_up = 0
                    else:
                        break

                # 回调概率 = 基础 3% + 连涨/均涨幅加成
                base_prob = 0.03

                if candle_consec_up >= 4:
                    up_factor = min(0.15, (candle_consec_up - 3) * 0.04)
                    base_prob += up_factor

                if avg_change > 1.5:
                    change_factor = min(0.1, (avg_change - 1.5) * 0.04)
                    base_prob += change_factor

                if random.random() < 0.15:
                    sentiment = random.choice([-1, 1])
                    sentiment_pct = random.uniform(0.008, 0.025)  # 0.8%~2.5%
                    final_price = final_price * (1 + Decimal(str(sentiment * sentiment_pct)))
                    logger.info(f"[stock] 市场情绪变化: stock={stock.code}, "
                               f"{'上涨' if sentiment > 0 else '下跌'}{sentiment_pct*100:.1f}%")

                if random.random() < base_prob:
                    if avg_change > 2.0:  # 提高触发门槛
                        callback_pct = random.uniform(0.01, 0.03)  # 1%~3%（降低）
                    elif avg_change > 1.5:
                        callback_pct = random.uniform(0.008, 0.02)  # 0.8%~2%（降低）
                    else:
                        callback_pct = random.uniform(0.005, 0.012)  # 0.5%~1.2%（降低）

                    final_price = final_price * (1 - Decimal(str(callback_pct)))
                    logger.info(f"[stock] 技术性回调: stock={stock.code}, "
                               f"近期平均涨幅{avg_change:.1f}%, 回调{callback_pct*100:.1f}%")

        # 波动后强制夹回涨跌停：须用非对称限幅，否则可绕过防连板约束
        upper_bound = last_close_dec * (Decimal("1") + Decimal(str(cfg.get("upperLimitPct", limit_pct))))
        lower_bound = last_close_dec * (Decimal("1") - Decimal(str(cfg.get("lowerLimitPct", limit_pct))))
        final_price = max(lower_bound, min(upper_bound, final_price))

        # final 转 Decimal，供后续 candle 入库/K 线保存等 Decimal 化路径
        price["final"] = final_price

        # 撮合不成交 → 同样走趋势漂移并推进轮次，避免长期平盘、K 线留空洞
        if not match["matched"]:
            drift_data = {
                "happiness": float(effective_happiness(stock, field_map)),
                "currentCarbon": float(effective_carbon(stock, field_map)),
                "industryAvgCarbon": float(effective_industry_avg_carbon(stock, field_map)),
                "happinessImpact": stock_config["happinessImpact"],
                "carbonImpact": stock_config["carbonImpact"],
                "carbonSaturateRatio": stock_config["carbonSaturateRatio"],
                "maxMovePct": stock_config["maxMovePct"],
            }
            new_round, candle = _advance_round_flat(stock, competition_id, limit_pct, drift_data)
            return {
                "stockId": stock.id,
                "code": stock.code,
                "round": new_round,
                "skipped": True,
                "matched": False,
                "finalPrice": float(candle["close"]),
                "pressure": price["pressure"],
                "drift": price["drift"],
                "theoretical": price["theoretical"],
                "buyQty": match["totalBuyQty"],
                "sellQty": match["totalSellQty"],
                "buyAmount": match["totalBuyAmount"],
                "sellAmount": match["totalSellAmount"],
                "candle": candle,
            }

        # 账户现金 / 持仓运行时快照（统一 Decimal，规避 float 累计误差）
        cash_map: dict[int, Decimal] = {}
        account_objs: dict[int, StockFundsAccount] = {}
        for o in orders:
            if o.funds_account_id not in cash_map:
                acc = o.funds_account
                account_objs[o.funds_account_id] = acc
                if acc.bind_field_id and acc.company_id:
                    v = resolve_field_value_or_default(acc.company_id, acc.bind_field_id)
                    cash_map[o.funds_account_id] = (
                        Decimal(str(v)) if v is not None else Decimal(str(acc.cash_balance))
                    )
                else:
                    cash_map[o.funds_account_id] = Decimal(str(acc.cash_balance))

        account_ids = list(cash_map.keys())
        holding_map: dict[int, dict] = {}
        for h in StockHolding.objects.filter(stock_id=stock.id, funds_account_id__in=account_ids):
            holding_map[h.funds_account_id] = {
                "shares": Decimal(str(h.shares)),
                "costPrice": Decimal(str(h.cost_price)),
            }
        touched_accounts: set[int] = set()

        # 价格-时间优先撮合
        buys = sorted(
            [o for o in orders if o.side == "BUY"],
            key=lambda o: (-o.price, o.created_at),
        )
        sells = sorted(
            [o for o in orders if o.side == "SELL"],
            key=lambda o: (o.price, o.created_at),
        )
        buy_rem: dict[int, Decimal] = {o.id: Decimal(str(o.quantity)) for o in buys}
        sell_rem: dict[int, Decimal] = {o.id: Decimal(str(o.quantity)) for o in sells}
        filled: dict[int, Decimal] = {}
        trade_price = Decimal(str(match["tradePrice"])) if match.get("tradePrice") is not None else None

        bi = 0
        si = 0
        trade_prices: list[Decimal] = []
        while bi < len(buys) and si < len(sells):
            buy = buys[bi]
            sell = sells[si]
            if buy.price < sell.price:
                break
            qty = min(buy_rem[buy.id], sell_rem[sell.id])
            # 统一中点价 tradePrice 可能越出单笔限价（买挂 9.2、卖挂 9 → 中点 9.5 会让买方
            # 高于自己限价买入），故逐对成交价夹到 [卖价, 买价]（已保证 sell.price <= buy.price）。
            pair_price = min(
                max(trade_price, Decimal(str(sell.price))),
                Decimal(str(buy.price)),
            )
            buy_cash = cash_map[buy.funds_account_id]
            if qty * pair_price > buy_cash + EPS:
                qty = buy_cash / pair_price
                if qty <= EPS:
                    buy_rem[buy.id] = Decimal("0")
                    bi += 1
                    continue
            sell_hold = holding_map.get(sell.funds_account_id)
            sell_shares = sell_hold["shares"] if sell_hold else Decimal("0")
            if qty > sell_shares + EPS:
                qty = sell_shares
                if qty <= EPS:
                    sell_rem[sell.id] = Decimal("0")
                    si += 1
                    continue
            # 6 位小数微调（保留买卖双方分摊精度，不入账）
            qty = (qty * Decimal("1000000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / Decimal("1000000")
            trade_prices.append(pair_price)

            cash_map[buy.funds_account_id] = cash_map[buy.funds_account_id] - qty * pair_price
            bh = holding_map.get(buy.funds_account_id, {"shares": Decimal("0"), "costPrice": Decimal("0")})
            new_shares = bh["shares"] + qty
            new_cost = (
                (bh["shares"] * bh["costPrice"] + qty * pair_price) / new_shares
                if new_shares > 0
                else pair_price
            )
            holding_map[buy.funds_account_id] = {"shares": new_shares, "costPrice": new_cost}
            cash_map[sell.funds_account_id] = cash_map[sell.funds_account_id] + qty * pair_price
            sh = holding_map.get(sell.funds_account_id, {"shares": Decimal("0"), "costPrice": Decimal("0")})
            holding_map[sell.funds_account_id] = {
                "shares": max(Decimal("0"), sh["shares"] - qty),
                "costPrice": sh["costPrice"],
            }

            touched_accounts.add(buy.funds_account_id)
            touched_accounts.add(sell.funds_account_id)
            filled[buy.id] = filled.get(buy.id, Decimal("0")) + qty
            filled[sell.id] = filled.get(sell.id, Decimal("0")) + qty

            buy_rem[buy.id] = buy_rem[buy.id] - qty
            sell_rem[sell.id] = sell_rem[sell.id] - qty
            if buy_rem[buy.id] <= EPS:
                bi += 1
            if sell_rem[sell.id] <= EPS:
                si += 1

        candle = build_candle(
            stock.current_price, price["final"], stock.round + 1,
            price["theoretical"], cfg["limitPct"], upper_pct, lower_pct,
            trade_high=float(max(trade_prices)) if trade_prices else None,
            trade_low=float(min(trade_prices)) if trade_prices else None,
        )
        new_round = stock.round + 1

        # 现金：绑定字段的账户写字段值，否则写账户余额。
        # touched_field_companies 为本次写了绑定字段的公司，结算后需重算引用它的计算字段。
        touched_field_companies: set[int] = set()
        for acc_id, cash in cash_map.items():
            acc = account_objs.get(acc_id)
            rounded_cash = round2(cash)
            if acc is not None and acc.bind_field_id and acc.company_id:
                write_field_value_in_tx(acc.company_id, acc.bind_field_id, str(rounded_cash))
                touched_field_companies.add(acc.company_id)
            # 同步账户余额列：绑定字段账户列表展示依赖 cash_balance，否则会显示陈旧值
            if acc is not None:
                StockFundsAccount.objects.filter(pk=acc_id).update(cash_balance=rounded_cash)
        if touched_field_companies:
            # 现金常被计算字段引用（如「总资产 = 现金 + 持仓市值」），不重算会一直停在旧值
            # （多库适配点 5：旧 emit_resource_changed 广播改为 §4.3 推送只当信号）。
            _recompute_calc_after_cash_write(touched_field_companies)

        for acc_id in touched_accounts:
            h = holding_map.get(acc_id)
            if h is None:
                continue
            if h["shares"] > EPS:
                StockHolding.objects.update_or_create(
                    funds_account_id=acc_id,
                    stock_id=stock.id,
                    defaults={
                        "shares": round2(h["shares"]),
                        "cost_price": round2(h["costPrice"]),
                    },
                )
            else:
                StockHolding.objects.filter(funds_account_id=acc_id, stock_id=stock.id).delete()

        for o in orders:
            f = filled.get(o.id, Decimal("0"))
            if f > EPS:
                remaining = Decimal(str(o.quantity)) - f
                if remaining <= EPS:
                    StockOrder.objects.filter(pk=o.id).update(status="FILLED")
                else:
                    StockOrder.objects.filter(pk=o.id).update(
                        quantity=round2(remaining),
                        amount=round2(Decimal(str(o.price)) * remaining),
                    )

        # K 线字段为 snake_case（build_candle 返回驼峰）；成交量取买单侧合计（买卖配对）
        total_volume = Decimal("0")
        for buy_order in buys:
            total_volume += filled.get(buy_order.id, Decimal("0"))

        StockCandle.objects.create(
            stock_id=stock.id,
            open=candle["open"],
            high=candle["high"],
            low=candle["low"],
            close=candle["close"],
            change_pct=candle["changePct"],
            round=candle["round"],
            volume=round2(total_volume),
        )
        Stock.objects.filter(pk=stock.id).update(current_price=price["final"], round=new_round)

        # 旧轮订单不直接撤销：价格仍在新限幅内的保持有效并升级轮次，避免跨轮以过时
        # 价限成交（下单时的 ±10% 限制随轮次失效）。
        from decimal import Decimal as D

        old_orders = StockOrder.objects.filter(
            stock_id=stock.id,
            status="PENDING",
            round__lt=new_round,
        )

        if old_orders.exists():
            current_price = price["final"]
            upper_limit = current_price * (1 + D(str(cfg["upperLimitPct"])))
            lower_limit = current_price * (1 - D(str(cfg["lowerLimitPct"])))

            cancelled_count = 0
            for order in old_orders:
                order_price = D(str(order.price))
                if order_price < lower_limit or order_price > upper_limit:
                    order.status = "CANCELLED"
                    order.save(update_fields=["status"])
                    cancelled_count += 1
                else:
                    order.round = new_round
                    order.save(update_fields=["round"])

        return {
            "stockId": stock.id,
            "code": stock.code,
            "round": new_round,
            "skipped": False,
            "matched": match["matched"],
            "tradePrice": trade_price,
            "finalPrice": price["final"],
            "theoretical": price["theoretical"],
            "pressure": price["pressure"],
            "drift": price["drift"],
            "usedTradePrice": price["usedTradePrice"],
            "buyQty": match["totalBuyQty"],
            "sellQty": match["totalSellQty"],
            "buyAmount": match["totalBuyAmount"],
            "sellAmount": match["totalSellAmount"],
            "mmIntervened": mm_intervened,
            "mmOrderCount": mm_count,
            "candle": candle,
        }


_advance_locks: dict[int, threading.Lock] = {}
_advance_locks_guard = threading.Lock()


def _try_acquire_advance_lock(competition_id: int) -> bool:
    """尝试获取推进锁（非阻塞）。进程内 threading.Lock，不跨进程（H6）。

    单进程 ASGI 足够；扩到多 worker 需换跨进程互斥（Redis / Postgres 咨询锁）。
    """
    with _advance_locks_guard:
        lock = _advance_locks.get(competition_id)
        if lock is None:
            lock = threading.Lock()
            _advance_locks[competition_id] = lock
        return lock.acquire(blocking=False)


def _release_advance_lock(competition_id: int) -> None:
    """释放推进锁（只释放一次：旧实现重复 release 会误释放他人刚获取的锁）。"""
    with _advance_locks_guard:
        lock = _advance_locks.get(competition_id)
        if lock is not None:
            try:
                lock.release()
            except RuntimeError:
                pass


def load_stock_config(competition_id: int) -> dict:
    """解析比赛级 stockConfig（全局库 Competition.stock_config），缺失回退默认值。"""
    from apps.global_.competitions.models import Competition

    comp = Competition.objects.filter(pk=competition_id).first() if competition_id else None
    raw = getattr(comp, "stock_config", None) if comp else None
    return resolve_stock_config(raw if isinstance(raw, dict) else None)


def advance_round(
    competition_id: int,
    stock_ids: list[int] | None = None,
    market_maker: dict | None = None,
    stock_config: dict | None = None,
    operator=None,
) -> dict:
    """推进一轮：对比赛内（或指定）股票逐只撮合、定价、生成 K 线（契约 §3 编排入口）。

    撮合→定价→K线→做市商→推进 round 全在单事务内，异常整体回滚不落半账（§1/§3）；
    比赛库 alias 由 thread-local get_competition_alias() 提供，事务经 comp_atomic 落库。
    """
    from .models import Stock, StockCandle

    if not _try_acquire_advance_lock(competition_id):
        raise StockError(
            "轮次推进正在进行中，请稍候", code=409, status_code=409
        )
    try:
        results: list = []

        base_config = load_stock_config(competition_id)
        if stock_config:
            cfg = dict(base_config)
            cfg.update(stock_config)
        else:
            cfg = base_config
        mm_config = market_maker

        total_mm_orders = 0

        # 整轮一个事务（H6）：要么全部成功要么整体回滚，避免半场崩溃的脏写；
        # 事务内对 Stock 行加 select_for_update，与进程内锁形成「进程内 + DB」双重防护（#16）。
        with comp_atomic():
            qs = Stock.objects.all()
            if stock_ids:
                qs = qs.filter(pk__in=stock_ids)
            if connection.vendor != "sqlite":
                qs = qs.select_for_update()
            stocks = list(qs.order_by("code"))
            field_map = resolve_field_value_map(competition_id)
            # 一次性批量构建 PE 联动值映射，避免推进轮次时对每只股票逐一查库（H4）
            pb_value_map = _build_pb_value_map(stocks)

            # 批量获取每只股票的最近K线（避免 N+1 查询）
            stock_ids_list = [s.id for s in stocks]
            recent_candles_map: dict[int, list] = {sid: [] for sid in stock_ids_list}
            if stock_ids_list:
                recent_candles = list(
                    StockCandle.objects.filter(
                        stock_id__in=stock_ids_list,
                    ).order_by("stock_id", "-round")
                )
                for candle in recent_candles:
                    if len(recent_candles_map[candle.stock_id]) < 3:
                        recent_candles_map[candle.stock_id].append(candle)

            for stock in stocks:
                apply_pb_round(stock, pb_value_map)
                recent = recent_candles_map.get(stock.id, [])
                up = 0
                down = 0
                for c in recent:
                    if c.change_pct >= 9.9:
                        up += 1
                        down = 0
                    elif c.change_pct <= -9.9:
                        down += 1
                        up = 0
                    else:
                        break
                r = advance_one_stock(
                    stock, competition_id, field_map, cfg, up, down, mm_config,
                    float(recent[0].change_pct) if recent else 0.0, stocks,
                )
                if r:
                    results.append(r)
                    total_mm_orders += r.get("mmOrderCount", 0)

        advanced = sum(1 for x in results if not x.get("skipped"))

        # 审计留痕（多库适配点 7：旧 apps.common.audit.log_write → 比赛内审计服务）。
        try:
            from apps.competition.audit import services as audit_services

            audit_services.log_action(
                'STOCK_ADVANCE_ROUND',
                actor=operator,
                target=str(competition_id),
                payload={
                    "advanced": advanced,
                    "skipped": len(results) - advanced,
                    "marketMakerOrders": total_mm_orders,
                },
            )
        except Exception:  # noqa: BLE001 - 审计失败不阻断推进结果
            logger.warning("[stock] advance_round 审计写入失败", exc_info=True)

        # 推送信号（契约 §4.3：轮次推进后广播 {type:'stock-updated'}，只当信号不带数据）
        new_round = max((x.get("round") or 0 for x in results), default=0)
        try:
            from .services import broadcast_stock_updated

            broadcast_stock_updated(competition_id, new_round)
        except Exception:  # noqa: BLE001 - 推送失败静默（§4.3 防风暴，失败不影响业务）
            logger.warning("[stock] advance_round 广播失败", exc_info=True)

        return {
            "advanced": advanced,
            "skipped": len(results) - advanced,
            "results": results,
            "marketMakerOrders": total_mm_orders,
        }
    finally:
        _release_advance_lock(competition_id)
