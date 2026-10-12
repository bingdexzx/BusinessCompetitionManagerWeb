"""股票应用配置（契约 §2：apps/competition/stock，比赛库模型）。

语义来源：《股票模块与同步优化.md》§2 领域模型；app label 取 'stock'
（多库路由 apps.competition.routing.COMPETITION_APPS 按 label 识别比赛域）。
"""

from django.apps import AppConfig


class StockConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.competition.stock'
    label = 'stock'
    verbose_name = '股票'
