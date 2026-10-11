from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'to_user_id', 'kind', 'title', 'read_at', 'created_at')
