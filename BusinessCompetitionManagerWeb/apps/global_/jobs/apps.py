from django.apps import AppConfig


class JobsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.global_.jobs'
    label = 'jobs'
    verbose_name = '后台任务'
