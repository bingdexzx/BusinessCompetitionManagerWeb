from django.contrib import admin

from .models import FiscalYear, FiscalYearBackup


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ('id', 'year', 'status', 'opened_at', 'closed_at')


@admin.register(FiscalYearBackup)
class FiscalYearBackupAdmin(admin.ModelAdmin):
    list_display = ('id', 'fiscal_year', 'company', 'created_at')
