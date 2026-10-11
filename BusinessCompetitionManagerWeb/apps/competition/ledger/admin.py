from django.contrib import admin

from .models import ContractFreeze


@admin.register(ContractFreeze)
class ContractFreezeAdmin(admin.ModelAdmin):
    list_display = ('id', 'contract', 'company', 'field_key', 'frozen_at', 'unfrozen_at')
