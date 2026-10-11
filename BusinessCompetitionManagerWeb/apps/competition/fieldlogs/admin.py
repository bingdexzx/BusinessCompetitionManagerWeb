from django.contrib import admin

from .models import FieldLog


@admin.register(FieldLog)
class FieldLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'occurred_at', 'company', 'field_key', 'event', 'source', 'operator_username', 'trace_id')

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
