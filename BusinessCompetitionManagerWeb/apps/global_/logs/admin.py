from django.contrib import admin

from .models import Device, NetworkLog


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'os', 'browser', 'screen', 'ip', 'first_login_at', 'last_login_at')
    search_fields = ('user__username',)


@admin.register(NetworkLog)
class NetworkLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'occurred_at', 'method', 'path', 'status', 'duration_ms', 'user', 'competition_id', 'ip')
    list_filter = ('method', 'status')
    search_fields = ('path', 'trace_id', 'user__username')

    def has_delete_permission(self, request, obj=None):
        return False  # 只增不删（决策 D20）

    def has_change_permission(self, request, obj=None):
        return False
