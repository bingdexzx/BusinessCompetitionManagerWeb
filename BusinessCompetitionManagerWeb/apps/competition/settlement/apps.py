from django.apps import AppConfig


class SettlementConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.competition.settlement'
    label = 'settlement'
    verbose_name = '结算与评分'
