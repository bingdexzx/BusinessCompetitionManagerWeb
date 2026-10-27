from django.contrib import admin

from apps.global_.files.models import MapBackground


@admin.register(MapBackground)
class MapBackgroundAdmin(admin.ModelAdmin):
    list_display = ('competition', 'url', 'file_path', 'updated_at')
    search_fields = ('url', 'file_path')
