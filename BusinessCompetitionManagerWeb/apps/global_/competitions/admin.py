from django.contrib import admin

from .models import Competition


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'status', 'db_name', 'host_school', 'location', 'created_by', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'location')
