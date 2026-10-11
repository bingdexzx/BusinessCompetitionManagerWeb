from django.contrib import admin

from .models import Package, PackagePlugin


class PackagePluginInline(admin.TabularInline):
    model = PackagePlugin
    extra = 0


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('id', 'competition', 'file_name', 'status', 'sha256', 'created_by_username', 'created_at')
    list_filter = ('status',)
    inlines = [PackagePluginInline]

    def has_delete_permission(self, request, obj=None):
        return False  # 上传审计留存（§9.4）
