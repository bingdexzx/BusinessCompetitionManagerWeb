from django.apps import AppConfig


class BasedataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.competition.basedata'
    label = 'basedata'
    verbose_name = '基础数据'
