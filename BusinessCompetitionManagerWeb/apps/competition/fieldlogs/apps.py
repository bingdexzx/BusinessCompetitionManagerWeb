from django.apps import AppConfig


class FieldlogsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.competition.fieldlogs'
    label = 'fieldlogs'
    verbose_name = '字段日志'
