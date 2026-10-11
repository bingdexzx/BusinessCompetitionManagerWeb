from django.apps import AppConfig


class LedgerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.competition.ledger'
    label = 'ledger'
    verbose_name = '落账与冻结'
