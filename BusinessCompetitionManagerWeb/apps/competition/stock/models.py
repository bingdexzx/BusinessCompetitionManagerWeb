"""股票领域模型（契约 §2 五张表：Stock / StockFundsAccount / StockHolding /
StockOrder / StockCandle）；比赛库模型（多库架构 §5.2）。

多库适配：不建跨库外键（user_id/company_id/pb_company_id/pb_field_id/bind_field_id 存
BigIntegerField 整数引用）；同库 FK 保留；不设 competition 外键（一个比赛一个库）。

金额一律 DecimalField(max_digits=60, decimal_places=4)：浮点累计误差会让账户与账面余额对不上。
所有表 updated_at 建索引，供 §4.2 delta 的 ORDER BY updated_at, id keyset 拉取。
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
    # 绑定区域总览卡片（实时引用）：单体 JSON {region, cardId}，均值用数组 [{region,cardId},...]
    carbon_field_ref = models.CharField('碳排绑定引用', max_length=255, null=True, blank=True)
    happiness_field_ref = models.CharField('幸福度绑定引用', max_length=255, null=True, blank=True)
    industry_avg_carbon_refs = models.CharField(
        '行业碳排均值绑定引用', max_length=1024, null=True, blank=True,
    )
    # 行业 PE 联动：pbCompanyId + pbFieldId 同时非空为联动模式，否则随机模式
    pb_company_id = models.BigIntegerField('PE 联动公司 ID', null=True, blank=True)
    pb_field_id = models.BigIntegerField('PE 联动产业字段 ID', null=True, blank=True)
    pb_random = models.FloatField('随机 PE', null=True, blank=True)
    init_price = models.DecimalField('初始价', max_digits=60, decimal_places=4)
    current_price = models.DecimalField('当前价', max_digits=60, decimal_places=4)
    round = models.IntegerField('轮次', default=0)
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
            models.Index(fields=['updated_at'], name='idx_stock_stocks_updated'),
        ]

    def __str__(self):
        return f'{self.code} {self.name}'


class StockFundsAccount(models.Model):
    """资金账户（§2 StockFundsAccount）：`unique(name)`。"""

    OWNER_CHOICES = [('COMPANY', 'COMPANY'), ('USER', 'USER')]

    name = models.CharField('账户名', max_length=255)
    owner_type = models.CharField('归属类型', max_length=16, choices=OWNER_CHOICES)
    # ownerType 决定引用 Company.id 还是全局库 User.id，均仅 int 引用、不建跨库外键
    company_id = models.BigIntegerField('公司 ID', null=True, blank=True)
    user_id = models.BigIntegerField('用户 ID（全局库）', null=True, blank=True)
    # 玩家现金账户最关键：多笔成交后浮点累计误差可达万元级，Decimal 精确到分
    cash_balance = models.DecimalField(
        '现金余额', max_digits=60, decimal_places=4, default=1_000_000,
    )
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
    # 持股数/成本价用 Decimal（撮合累加会漂）；shares 非负约束防撮合 bug 产生负持仓（P1-#6）
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
    open = models.DecimalField('开盘', max_digits=60, decimal_places=4)
    high = models.DecimalField('最高', max_digits=60, decimal_places=4)
    low = models.DecimalField('最低', max_digits=60, decimal_places=4)
    close = models.DecimalField('收盘', max_digits=60, decimal_places=4)
    change_pct = models.DecimalField('涨跌幅 %', max_digits=60, decimal_places=4)
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
