from django.apps import AppConfig


class InmailConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.global_.messages'
    label = 'inmail'  # 避免与 django.contrib.messages 的 label 冲突
    verbose_name = '站内信'
