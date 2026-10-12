"""股票模型管理后台（契约 §2 五张表；供管理员维护股票/账户基础数据）。"""

from django.contrib import admin

from .models import (
    Stock, StockCandle, StockFundsAccount, StockHolding, StockOrder,
)


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'current_price', 'init_price', 'round', 'company', 'updated_at')
    search_fields = ('code', 'name')


@admin.register(StockFundsAccount)
class StockFundsAccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'owner_type', 'company_id', 'user_id', 'cash_balance', 'bind_field_id')
    search_fields = ('name',)


@admin.register(StockHolding)
class StockHoldingAdmin(admin.ModelAdmin):
    list_display = ('id', 'funds_account', 'stock', 'shares', 'cost_price', 'updated_at')


@admin.register(StockOrder)
class StockOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'stock', 'funds_account', 'side', 'price', 'quantity', 'status', 'round', 'created_at')
    list_filter = ('status', 'side')


@admin.register(StockCandle)
class StockCandleAdmin(admin.ModelAdmin):
    list_display = ('id', 'stock', 'round', 'open', 'high', 'low', 'close', 'change_pct', 'volume')
