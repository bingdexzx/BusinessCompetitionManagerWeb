from django.contrib import admin

from .models import Competition


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    """竞赛信息后台管理"""

    list_display = ('id', 'name', 'start_date', 'created_at')
    list_display_links = ('id', 'name')
    search_fields = ('name',)
