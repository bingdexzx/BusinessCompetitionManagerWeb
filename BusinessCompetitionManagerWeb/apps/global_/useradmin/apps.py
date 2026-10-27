from django.apps import AppConfig


class UserAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.global_.useradmin'
    label = 'useradmin'
    verbose_name = '用户管理'
