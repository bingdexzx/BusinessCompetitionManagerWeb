from django.contrib import admin

from .models import PluginRegistry


@admin.register(PluginRegistry)
class PluginRegistryAdmin(admin.ModelAdmin):
    list_display = ('id', 'kind', 'key', 'name', 'version', 'sha256', 'uploaded_by_username', 'created_at')
    list_filter = ('kind',)
    search_fields = ('key', 'name')

    def has_delete_permission(self, request, obj=None):
        return False  # 插件版本不可变（§5.4）
