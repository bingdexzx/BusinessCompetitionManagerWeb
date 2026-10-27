"""股票领域模型（契约 §2 五张表：Stock / StockFundsAccount / StockHolding /
StockOrder / StockCandle）。比赛库模型（多库架构 §5.2）。

语义来源：
- 《股票模块与同步优化.md》§2 领域模型表（字段与约束以此为准）；
- 旧系统 backend/apps/stock/models.py（领域语义、Decimal 金额口径、shares 非负约束）。

多库适配（§2「沿用旧系统领域（适配多库）」）：
- **不建跨库外键**：user_id / company_id / pb_company_id / pb_field_id / bind_field_id
  一律 BigIntegerField 存整数引用（全局库用户、比赛库公司/产业字段的 ID）；
- **同库 FK 保留**：Stock.company → companies.Company（on_delete=SET_NULL），
  StockHolding/StockOrder/StockCandle → 资金账户/股票（同库级联）；
- 不设 competition 外键：一个比赛一个库（comp_<id>），比赛归属由库本身决定。

金额一律 DecimalField(max_digits=60, decimal_places=4)（§2：股本/净利润/价格/
现金/持仓/委托必须精确，浮点累计误差会让玩家账户与账面余额对不上；max_digits=60
容纳亿级，decimal_places=4 给撮合误差留余量）。

增量同步（§4.2）：所有表 updated_at（auto_now）建索引
``idx_stock_<table>_updated``，delta 按 ``ORDER BY updated_at, id`` keyset 拉取。
"""

from django.db import models


class Stock(models.Model):
    """股票（§2 Stock）：`unique(code)`。"""

    code = models.CharField('股票代码', max_length=64)
    name = models.CharField('股票名称', max_length=255)
    # 基础信息（万股 / 万元）——股本/净利润/价格必须精确（§2 Decimal 口径）
    total_shares = models.DecimalField('总股本', max_digits=60, decimal_places=4)
    init_net_profit = models.DecimalField('初始净利润', max_digits=60, decimal_places=4)
    # PE / 碳排 / 幸福度：衍生指标（来自产业计算图），浮点足够（旧系统口径）
    industry_pe = models.FloatField('行业 PE')
    current_carbon = models.FloatField('当前碳排')
    industry_avg_carbon = models.FloatField('行业平均碳排')
    happiness = models.FloatField('幸福度')
    # 绑定区域总览卡片（实时引用）：JSON 字符串 {region, cardId}
    carbon_field_ref = models.CharField('碳排绑定引用', max_length=255, null=True, blank=True)
    happiness_field_ref = models.CharField('幸福度绑定引用', max_length=255, null=True, blank=True)
    # 行业碳排均值绑定的区域总览卡片引用数组 JSON [{region,cardId},...]
    industry_avg_carbon_refs = models.CharField(
        '行业碳排均值绑定引用', max_length=1024, null=True, blank=True,
    )
    # 行业 PE 联动：pbCompanyId + pbFieldId 同时非空为联动模式，否则随机模式
    pb_company_id = models.BigIntegerField('PE 联动公司 ID', null=True, blank=True)
    pb_field_id = models.BigIntegerField('PE 联动产业字段 ID', null=True, blank=True)
    pb_random = models.FloatField('随机 PE', null=True, blank=True)
    # 价格用 Decimal，避免浮点误差累积
    init_price = models.DecimalField('初始价', max_digits=60, decimal_places=4)
    current_price = models.DecimalField('当前价', max_digits=60, decimal_places=4)
    round = models.IntegerField('轮次', default=0)
    # 关联商赛公司（同库 FK 保留，SET_NULL）
    company = models.ForeignKey(
        'companies.Company',
        verbose_name='关联公司',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stocks',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '股票'
        verbose_name_plural = '股票'
        db_table = 'stocks'
        constraints = [
            models.UniqueConstraint(fields=['code'], name='uniq_stock_code'),
        ]
        indexes = [
            # 增量同步（§4.2 delta：updated_at keyset）
            models.Index(fields=['updated_at'], name='idx_stock_stocks_updated'),
        ]

    def __str__(self):
        return f'{self.code} {self.name}'


class StockFundsAccount(models.Model):
    """资金账户（§2 StockFundsAccount）：`unique(name)`。"""

    OWNER_CHOICES = [('COMPANY', 'COMPANY'), ('USER', 'USER')]

    name = models.CharField('账户名', max_length=255)
    owner_type = models.CharField('归属类型', max_length=16, choices=OWNER_CHOICES)
    # ownerType=COMPANY 时指向 Company.id（仅 int 引用，不建跨库外键）
    company_id = models.BigIntegerField('公司 ID', null=True, blank=True)
    # ownerType=USER 时指向全局库 User.id（仅 int 引用）
    user_id = models.BigIntegerField('用户 ID（全局库）', null=True, blank=True)
    # 玩家现金账户最关键：多笔成交后浮点累计误差可达万元级，Decimal 精确到分
    cash_balance = models.DecimalField(
        '现金余额', max_digits=60, decimal_places=4, default=1_000_000,
    )
    # 绑定产业字段 ID（仅公司账户），现金将同步该字段值（仅 int 引用）
    bind_field_id = models.BigIntegerField('绑定产业字段 ID', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '资金账户'
        verbose_name_plural = '资金账户'
        db_table = 'stock_funds_accounts'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_stock_funds_account_name'),
        ]
        indexes = [
            # 索引名 ≤30 字符（models.E034 跨库兼容约束）
            models.Index(fields=['updated_at'], name='idx_stock_funds_acc_updated'),
            # owner 可见性裁剪（§4.2：orders/holdings/accounts 只回本人的）
            models.Index(fields=['owner_type', 'user_id'], name='idx_stock_funds_acc_owner'),
        ]

    def __str__(self):
        return self.name


class StockHolding(models.Model):
    """持仓（§2 StockHolding）：`unique(account, stock)`，shares ≥ 0。"""

    funds_account = models.ForeignKey(
        StockFundsAccount,
        verbose_name='资金账户',
        on_delete=models.CASCADE,
        related_name='holdings',
    )
    stock = models.ForeignKey(
        Stock,
        verbose_name='股票',
        on_delete=models.CASCADE,
        related_name='holdings',
    )
    # 持股数与成本价：撮合后累加场景，浮点会漂；Decimal 与资金账户配套。
    # P1-#6: shares 非负约束，防止撮合 bug 产生负持仓
    shares = models.DecimalField('持股数', max_digits=60, decimal_places=4, default=0)
    cost_price = models.DecimalField('成本价', max_digits=60, decimal_places=4)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '持仓'
        verbose_name_plural = '持仓'
        db_table = 'stock_holdings'
        constraints = [
            models.UniqueConstraint(
                fields=['funds_account', 'stock'], name='uniq_stock_holding_account_stock',
            ),
            models.CheckConstraint(
                condition=models.Q(shares__gte=0),
                name='stock_holding_shares_non_negative',
            ),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_stock_holdings_updated'),
        ]

    def clean(self):
        """P1-#6: 持仓量不能为负（旧系统语义）。"""
        from django.core.exceptions import ValidationError
        if self.shares is not None and self.shares < 0:
            raise ValidationError('持仓量不能为负')

    def __str__(self):
        return f'account={self.funds_account_id} stock={self.stock_id} shares={self.shares}'


class StockOrder(models.Model):
    """委托（§2 StockOrder）：玩家/做市商在某轮对某股票下的买卖委托。"""

    SIDE_CHOICES = [('BUY', 'BUY'), ('SELL', 'SELL')]
    STATUS_CHOICES = [
        ('PENDING', 'PENDING'), ('FILLED', 'FILLED'), ('CANCELLED', 'CANCELLED'),
    ]

    stock = models.ForeignKey(
        Stock, verbose_name='股票', on_delete=models.CASCADE, related_name='orders',
    )
    funds_account = models.ForeignKey(
        StockFundsAccount, verbose_name='资金账户', on_delete=models.CASCADE, related_name='orders',
    )
    side = models.CharField('方向', max_length=8, choices=SIDE_CHOICES)
    # 委托价格/数量/金额：撮合核心输入，必须精确
    price = models.DecimalField('委托价', max_digits=60, decimal_places=4)
    quantity = models.DecimalField('委托量', max_digits=60, decimal_places=4)
    amount = models.DecimalField('委托金额', max_digits=60, decimal_places=4)
    status = models.CharField(
        '状态', max_length=16, default='PENDING', choices=STATUS_CHOICES,
    )
    round = models.IntegerField('轮次', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '委托'
        verbose_name_plural = '委托'
        db_table = 'stock_orders'
        indexes = [
            # 撮合按 股票×轮次×状态 取单（engine.advance_one_stock）
            models.Index(fields=['stock', 'round', 'status'], name='idx_stock_orders_srs'),
            models.Index(fields=['updated_at'], name='idx_stock_orders_updated'),
        ]

    def __str__(self):
        return (
            f'{self.side} {self.quantity}@{self.price} '
            f'stock={self.stock_id} status={self.status}'
        )


class StockCandle(models.Model):
    """K 线（§2 StockCandle）：每轮每股票一根，`unique(stock, round)`。close = 本轮最终价。"""

    stock = models.ForeignKey(
        Stock, verbose_name='股票', on_delete=models.CASCADE, related_name='candles',
    )
    round = models.IntegerField('轮次')
    # K 线 OHLC 与涨跌幅：每轮计算结果，存 Decimal 与股价口径一致
    open = models.DecimalField('开盘', max_digits=60, decimal_places=4)
    high = models.DecimalField('最高', max_digits=60, decimal_places=4)
    low = models.DecimalField('最低', max_digits=60, decimal_places=4)
    close = models.DecimalField('收盘', max_digits=60, decimal_places=4)
    change_pct = models.DecimalField('涨跌幅 %', max_digits=60, decimal_places=4)
    # 成交量：本轮实际成交的股票数量
    volume = models.DecimalField('成交量', max_digits=60, decimal_places=4, default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'K 线'
        verbose_name_plural = 'K 线'
        db_table = 'stock_candles'
        constraints = [
            models.UniqueConstraint(fields=['stock', 'round'], name='uniq_stock_candle_stock_round'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_stock_candles_updated'),
        ]

    def __str__(self):
        return f'stock={self.stock_id} round={self.round} close={self.close}'
