from django.apps import AppConfig


class PluginsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.global_.plugins'
    label = 'plugins'
    verbose_name = 'Python 插件注册表'
