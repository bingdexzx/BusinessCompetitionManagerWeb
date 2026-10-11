from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.competition.audit'
    label = 'comp_audit'
    verbose_name = '比赛内审计'
