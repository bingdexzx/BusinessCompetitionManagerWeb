from django.apps import AppConfig


class SysconfigConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.global_.sysconfig'
    label = 'sysconfig'
    verbose_name = '系统设置（流量限制配置）'
