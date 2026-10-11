from django.apps import AppConfig


class MessagesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.competition.messages'
    label = 'comp_messages'
    verbose_name = '比赛内消息'
