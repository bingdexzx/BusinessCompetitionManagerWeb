"""股票模块单测（契约 §3 纯函数引擎 + §4.2 同步协议序列化）。

口径（任务 6）：**不依赖数据库**——撮合/定价/K 线/精度走纯函数，
同步协议走纯序列化函数（鸭子类型 stub），数据库组装路径不在此测。
"""

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.competition.stock import engine, services


def _stub_stock(**kw):
    """最小股票 stub（序列化函数按属性读取，不触库）。"""
    base = dict(
        id=1, code='SH600000', name='测试股份',
        total_shares=Decimal('5000'), init_net_profit=Decimal('10000'),
        industry_pe=20.0, current_carbon=100.0, industry_avg_carbon=100.0,
        happiness=50.0,
        carbon_field_ref=None, happiness_field_ref=None, industry_avg_carbon_refs=None,
        pb_company_id=None, pb_field_id=None, pb_random=None,
        company_id=None,
        init_price=Decimal('100.00'), current_price=Decimal('102.30'),
        round=3,
        created_at=datetime(2025, 1, 1, 8, 0, tzinfo=dt_timezone.utc),
        updated_at=datetime(2025, 1, 2, 9, 30, tzinfo=dt_timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ================================================================ 撮合（§3 compute_match）


class ComputeMatchTests(SimpleTestCase):
    """撮合预检：成交价=(最高买+最低卖)/2，是否成交=最高买>=最低卖（旧 engine.ts 语义）。"""

    def test_matched_trade_price_is_midpoint(self):
        result = engine.compute_match([
            {'side': 'BUY', 'price': 10, 'quantity': 100},
            {'side': 'BUY', 'price': 9, 'quantity': 50},
            {'side': 'SELL', 'price': 8, 'quantity': 80},
            {'side': 'SELL', 'price': 11, 'quantity': 30},
        ])
        self.assertTrue(result['matched'])
        self.assertEqual(result['highestBuy'], 10)
        self.assertEqual(result['lowestSell'], 8)
        self.assertEqual(result['tradePrice'], 9)  # (10 + 8) / 2
        self.assertEqual(result['totalBuyQty'], 150)
        self.assertEqual(result['totalSellQty'], 110)
        self.assertEqual(result['totalBuyAmount'], 10 * 100 + 9 * 50)
        self.assertEqual(result['totalSellAmount'], 8 * 80 + 11 * 30)

    def test_not_matched_when_spread_positive(self):
        result = engine.compute_match([
            {'side': 'BUY', 'price': 5, 'quantity': 10},
            {'side': 'SELL', 'price': 8, 'quantity': 10},
        ])
        self.assertFalse(result['matched'])
        self.assertIsNone(result['tradePrice'])

    def test_single_side_never_matches(self):
        only_buy = engine.compute_match([{'side': 'BUY', 'price': 10, 'quantity': 1}])
        only_sell = engine.compute_match([{'side': 'SELL', 'price': 10, 'quantity': 1}])
        self.assertFalse(only_buy['matched'])
        self.assertFalse(only_sell['matched'])
        self.assertEqual(only_buy['lowestSell'], 0)
        self.assertEqual(only_sell['highestBuy'], 0)

    def test_equal_price_matches(self):
        result = engine.compute_match([
            {'side': 'BUY', 'price': Decimal('9.20'), 'quantity': Decimal('10')},
            {'side': 'SELL', 'price': Decimal('9.20'), 'quantity': Decimal('10')},
        ])
        self.assertTrue(result['matched'])
        self.assertEqual(result['tradePrice'], Decimal('9.20'))

    def test_empty_orders(self):
        result = engine.compute_match([])
        self.assertFalse(result['matched'])
        self.assertIsNone(result['tradePrice'])
        self.assertEqual(result['totalBuyQty'], 0)


# ================================================================ 定价（§3 compute_price）


class ComputePriceTests(SimpleTestCase):
    """最终价：限幅（含防连板非对称限幅 S10）、净买压力、成交价加权。"""

    def _cfg(self, **overrides):
        cfg = engine.resolve_stock_config(None)
        cfg.update(overrides)
        return cfg

    def _factors(self, **overrides):
        factors = {
            'lastClose': 100.0,
            'buyQty': 1000.0,
            'sellQty': 0.0,
            'matched': True,
            'tradePrice': 100.0,
            'happiness': 50.0,
            'currentCarbon': 100.0,
            'industryAvgCarbon': 100.0,
        }
        factors.update(overrides)
        return factors

    def test_pressure_in_unit_range(self):
        p = engine.compute_pressure(1000.0, 0.0)
        self.assertGreater(p, -1.0)
        self.assertLess(p, 1.0)
        self.assertAlmostEqual(p, 1000.0 / 1001.0)
        self.assertEqual(engine.compute_pressure(0.0, 0.0), 0.0)

    def test_theoretical_moves_with_pressure(self):
        cfg = self._cfg()
        up = engine.compute_price(self._factors(), cfg)
        down = engine.compute_price(self._factors(buyQty=0.0, sellQty=1000.0), cfg)
        self.assertGreater(up['theoretical'], 100.0)
        self.assertLess(down['theoretical'], 100.0)

    def test_unmatched_flat_price(self):
        """未成交（单边无对手盘）→ 平盘：final = 上轮收盘（限幅内不动）。"""
        cfg = self._cfg()
        result = engine.compute_price(self._factors(matched=False, tradePrice=None), cfg)
        self.assertFalse(result['usedTradePrice'])
        self.assertEqual(result['final'], Decimal('100.00'))

    def test_final_clamped_by_upper_limit(self):
        cfg = self._cfg()
        result = engine.compute_price(self._factors(tradePrice=1000.0), cfg)
        self.assertTrue(result['usedTradePrice'])
        # 上限 = 100 × (1 + 10%) = 110.00
        self.assertEqual(result['final'], Decimal('110.00'))

    def test_final_clamped_by_lower_limit(self):
        cfg = self._cfg()
        result = engine.compute_price(
            self._factors(matched=True, tradePrice=1.0, buyQty=0.0, sellQty=1000.0), cfg,
        )
        # 下限 = 100 × (1 - 10%) = 90.00
        self.assertEqual(result['final'], Decimal('90.00'))

    def test_anti_streak_asymmetric_limit(self):
        """防连板 S10：上轮封板 → 本轮同侧限幅收紧（96% 且 ≤9.6%），对称侧不受影响。"""
        cfg = self._cfg(upperLimitPct=engine._ANTI_STREAK_CAP_PCT)
        result = engine.compute_price(self._factors(tradePrice=1000.0), cfg)
        self.assertEqual(result['final'], Decimal('109.60'))
        lower = engine.compute_price(
            self._factors(matched=True, tradePrice=1.0, buyQty=0.0, sellQty=1000.0),
            self._cfg(lowerLimitPct=engine._ANTI_STREAK_CAP_PCT),
        )
        self.assertEqual(lower['final'], Decimal('90.40'))

    def test_anti_streak_never_reaches_seal_threshold(self):
        """任意 limitPct 配置下，同侧收紧后的最大变动 < 9.9% 封板判定线。"""
        for limit in (0.1, 0.15, 0.3, 0.5):
            pct = min(limit * engine._ANTI_STREAK_FACTOR, engine._ANTI_STREAK_CAP_PCT)
            self.assertLess(pct, 0.099, f'limit={limit} 可能连板')

    def test_trade_price_weight_blend(self):
        cfg = self._cfg()
        result = engine.compute_price(self._factors(), cfg)
        theoretical = engine.compute_theoretical(100.0, result['pressure'], result['drift'], cfg['maxMovePct'])
        expected = engine.round2(cfg['tradePriceWeight'] * 100.0 + (1 - cfg['tradePriceWeight']) * theoretical)
        self.assertEqual(result['final'], expected)

    def test_carbon_drift_sign(self):
        self.assertEqual(engine.compute_carbon_drift(100.0, 100.0), 0.0)
        self.assertEqual(engine.compute_carbon_drift(0.0, 100.0), 1.0)
        self.assertLess(engine.compute_carbon_drift(200.0, 100.0), 0.0)
        self.assertEqual(engine.compute_carbon_drift(100.0, 0.0), 0.0)


# ================================================================ K 线 / 初始价（§3）


class CandleTests(SimpleTestCase):
    def test_flat_candle_bounds(self):
        candle = engine.build_candle(10.0, 10.0, 1, None, 0.1)
        self.assertEqual(candle['open'], 10.0)
        self.assertEqual(candle['close'], 10.0)
        self.assertEqual(candle['changePct'], 0.0)
        self.assertGreaterEqual(candle['high'], 10.0)
        self.assertLessEqual(candle['low'], 10.0)

    def test_candle_stays_within_limits(self):
        candle = engine.build_candle(10.0, 10.9, 2, theoretical=25.0, limit_pct=0.1)
        upper = float(engine.round2(Decimal('10') * Decimal('1.1')))
        lower = float(engine.round2(Decimal('10') * Decimal('0.9')))
        self.assertLessEqual(candle['high'], upper)
        self.assertGreaterEqual(candle['low'], lower)

    def test_candle_deterministic(self):
        a = engine.build_candle(10.0, 10.5, 7, theoretical=10.4, limit_pct=0.1)
        b = engine.build_candle(10.0, 10.5, 7, theoretical=10.4, limit_pct=0.1)
        self.assertEqual(a, b)  # candle_noise 确定性伪随机（可复现）

    def test_change_pct_precision(self):
        candle = engine.build_candle(10.0, 10.123456, 1, None, 0.1)
        self.assertEqual(candle['changePct'], 1.23)


class InitPriceTests(SimpleTestCase):
    def test_formula(self):
        # ROUND(10000*10000/5000/20, 2) = 1000.0
        self.assertEqual(engine.compute_init_price(10000, 5000, 20), 1000.0)

    def test_invalid_inputs_return_zero(self):
        self.assertEqual(engine.compute_init_price(10000, 5000, 0), 0)
        self.assertEqual(engine.compute_init_price(10000, 0, 20), 0)


# ================================================================ Decimal 精度（round2 大数安全）


class Round2PrecisionTests(SimpleTestCase):
    """旧事故回归：默认 context 28 位对 10^26+ 数值 quantize 抛 InvalidOperation
    被吞成 0（现金清零）；round2 在 localcontext(prec=70) 下必须精确保留。"""

    def test_huge_decimal_not_zeroed(self):
        v = Decimal('1234567890123456789012345678.5555')
        self.assertEqual(engine.round2(v), Decimal('1234567890123456789012345678.56'))

    def test_1e30_keeps_value(self):
        result = engine.round2(Decimal('1E+30'))
        self.assertNotEqual(result, Decimal('0'))
        self.assertEqual(result, Decimal('1E+30'))

    def test_cash_flow_no_float_drift(self):
        """万笔成交累加场景：Decimal 累加精确（旧浮点漂移回归）。"""
        cent = Decimal('0.01')
        total = sum((cent for _ in range(10000)), Decimal('0'))
        self.assertEqual(engine.round2(total), Decimal('100.00'))

    def test_half_up_rounding(self):
        self.assertEqual(engine.round2('2.675'), Decimal('2.68'))
        self.assertEqual(engine.round2(0.1 + 0.2), Decimal('0.30'))

    def test_invalid_input_returns_zero(self):
        self.assertEqual(engine.round2('abc'), Decimal('0'))
        self.assertEqual(engine.round2(None), Decimal('0'))


# ================================================================ 同步协议序列化（§4.2，纯函数）


class SyncSerializationTests(SimpleTestCase):
    def test_stock_thin_fields(self):
        """薄字段（§4.1/§4.2）：code/name/currentPrice/initPrice/round/updatedAt/涨跌幅。"""
        data = services.serialize_stock_thin(_stub_stock(), change_pct=1.23)
        self.assertEqual(
            set(data),
            {'id', 'code', 'name', 'currentPrice', 'initPrice', 'round', 'changePct', 'updatedAt'},
        )
        self.assertEqual(data['code'], 'SH600000')
        self.assertEqual(data['changePct'], 1.23)
        self.assertEqual(data['updatedAt'], '2025-01-02T09:30:00+00:00')

    def test_stock_detail_full_fields(self):
        data = services.serialize_stock_detail(_stub_stock())
        for key in (
            'totalShares', 'initNetProfit', 'industryPE', 'currentCarbon',
            'industryAvgCarbon', 'happiness', 'initPrice', 'currentPrice', 'round',
            'effectiveCurrentCarbon', 'effectiveHappiness', 'effectiveIndustryAvgCarbon',
            'effectivePb', 'pbMode', 'changePct', 'updatedAt',
        ):
            self.assertIn(key, data)
        self.assertEqual(data['pbMode'], 'random')

    def test_candle_fields(self):
        c = SimpleNamespace(
            id=9, stock_id=1, round=3,
            open=Decimal('10.00'), high=Decimal('10.50'), low=Decimal('9.90'),
            close=Decimal('10.30'), change_pct=Decimal('3.00'), volume=Decimal('1200'),
            updated_at=datetime(2025, 1, 2, 9, 30, tzinfo=dt_timezone.utc),
        )
        data = services.serialize_candle(c, stock_code='SH600000')
        self.assertEqual(data['stockCode'], 'SH600000')
        self.assertEqual(data['round'], 3)
        self.assertEqual(data['close'], Decimal('10.30'))
        self.assertEqual(data['updatedAt'], '2025-01-02T09:30:00+00:00')

    def test_order_fields(self):
        o = SimpleNamespace(
            id=5, stock_id=1, funds_account_id=2, side='BUY',
            price=Decimal('10.00'), quantity=Decimal('100'), amount=Decimal('1000.00'),
            status='PENDING', round=3,
            created_at=None, updated_at=None,
        )
        data = services.serialize_order(o, stock_code='SH600000')
        self.assertEqual(
            set(data),
            {'id', 'stockId', 'stockCode', 'fundsAccountId', 'side', 'price',
             'quantity', 'amount', 'status', 'round', 'createdAt', 'updatedAt'},
        )
        self.assertIsNone(data['createdAt'])

    def test_holding_and_account_fields(self):
        h = SimpleNamespace(
            id=1, funds_account_id=2, stock_id=1,
            shares=Decimal('100'), cost_price=Decimal('9.50'), updated_at=None,
        )
        data = services.serialize_holding(
            h, stock_code='SH600000', stock_name='测试股份', current_price=Decimal('10.00'),
        )
        self.assertEqual(data['marketValue'], Decimal('1000.00'))
        self.assertEqual(data['stockCode'], 'SH600000')

        a = SimpleNamespace(
            id=2, name='一队资金账户', owner_type='COMPANY', company_id=7,
            user_id=None, cash_balance=Decimal('1000000.00'), bind_field_id=3,
            created_at=None, updated_at=None,
        )
        account = services.serialize_account(a, field_balance=Decimal('999999.50'))
        self.assertEqual(account['ownerType'], 'COMPANY')
        self.assertEqual(account['fieldBalance'], Decimal('999999.50'))


class SyncProtocolTests(SimpleTestCase):
    """§4.2 协议语义：mode/serverTime/round/hasMore + 五集合、游标解析、limit 截断。"""

    def test_envelope_keys(self):
        payload = services.build_sync_envelope(
            mode='snapshot', server_time='2025-01-02T09:30:00+00:00', round_=12,
            has_more=False, stocks=[], candles=[], orders=[], holdings=[], accounts=[],
        )
        self.assertEqual(
            set(payload),
            {'mode', 'serverTime', 'round', 'hasMore', 'stocks', 'candles',
             'orders', 'holdings', 'accounts'},
        )
        self.assertEqual(payload['round'], 12)

    def test_since_empty_means_snapshot(self):
        self.assertIsNone(services.parse_sync_since(None))
        self.assertIsNone(services.parse_sync_since(''))
        self.assertEqual(services.sync_mode(None), 'snapshot')
        self.assertEqual(services.sync_mode(services.parse_sync_since('2025-01-02T09:30:00Z')), 'delta')

    def test_bad_since_falls_back_to_snapshot(self):
        """失败恢复（§4.2）：游标过期/异常 → 客户端回退 snapshot（解析失败视作空游标）。"""
        self.assertIsNone(services.parse_sync_since('not-a-time'))
        self.assertEqual(services.sync_mode(services.parse_sync_since('not-a-time')), 'snapshot')

    def test_limit_default_and_clamp(self):
        self.assertEqual(services.parse_sync_limit(None), 500)
        self.assertEqual(services.parse_sync_limit('abc'), 500)
        self.assertEqual(services.parse_sync_limit('10'), 10)
        self.assertEqual(services.parse_sync_limit('999999'), services.SYNC_MAX_LIMIT)
        self.assertEqual(services.parse_sync_limit('0'), 1)

    def test_clip_rows_sets_has_more(self):
        rows = [1, 2, 3]
        clipped, more = services.clip_sync_rows(rows, 2)
        self.assertEqual(clipped, [1, 2])
        self.assertTrue(more)
        clipped, more = services.clip_sync_rows(rows, 3)
        self.assertEqual(clipped, [1, 2, 3])
        self.assertFalse(more)
        clipped, more = services.clip_sync_rows([], 5)
        self.assertEqual(clipped, [])
        self.assertFalse(more)


class OwnerVisibilityTests(SimpleTestCase):
    """§4.2 可见性裁剪：orders/holdings/accounts 只回本人的（USER=本人 / COMPANY=所辖）。"""

    def test_user_account_only_self(self):
        user = SimpleNamespace(id=42)
        own = SimpleNamespace(owner_type='USER', user_id=42, company_id=None)
        other = SimpleNamespace(owner_type='USER', user_id=7, company_id=None)
        self.assertTrue(services.account_owned_by_user(own, user, set()))
        self.assertFalse(services.account_owned_by_user(other, user, set()))

    def test_company_account_needs_scope(self):
        user = SimpleNamespace(id=42)
        account = SimpleNamespace(owner_type='COMPANY', user_id=None, company_id=7)
        self.assertTrue(services.account_owned_by_user(account, user, {7, 8}))
        self.assertFalse(services.account_owned_by_user(account, user, {8}))
        self.assertTrue(services.account_owned_by_user(account, user, {'*'}))

    def test_unknown_owner_type_denied(self):
        user = SimpleNamespace(id=42)
        account = SimpleNamespace(owner_type='???', user_id=42, company_id=7)
        self.assertFalse(services.account_owned_by_user(account, user, {'*'}))


class SyncCursorTests(SimpleTestCase):
    """续拉游标语义（修复截断漏行）：截断时游标=已交付行边界回拨 1µs。"""

    def test_no_truncation_uses_now(self):
        from django.utils import timezone

        now = timezone.now()
        cursor = services.resolve_sync_server_time(
            now=now, truncated_boundaries=[], has_more=False)
        self.assertEqual(cursor, now.isoformat())

    def test_truncation_lowers_cursor_to_boundary(self):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        boundary = now - timedelta(seconds=5)
        cursor = services.resolve_sync_server_time(
            now=now, truncated_boundaries=[boundary], has_more=True)
        # 游标 = 边界 - 1µs → 续拉（updated_at > cursor）能覆盖边界同刻行与全部尾部行
        self.assertLess(cursor, boundary.isoformat())

    def test_multiple_truncated_collections_take_min(self):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        low = now - timedelta(seconds=30)
        high = now - timedelta(seconds=5)
        cursor = services.resolve_sync_server_time(
            now=now, truncated_boundaries=[high, low], has_more=True)
        self.assertLess(cursor, low.isoformat())
