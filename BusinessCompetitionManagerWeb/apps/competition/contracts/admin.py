from django.contrib import admin

from .models import Contract, ContractConfirmation, ContractFieldEffect, ContractModRequest


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('id', 'unified_number', 'contract_type_key', 'status', 'round_no', 'is_backfill', 'created_at')


@admin.register(ContractConfirmation)
class ContractConfirmationAdmin(admin.ModelAdmin):
    list_display = ('id', 'contract', 'party_role', 'confirmed_by_username', 'confirmed_at')


@admin.register(ContractModRequest)
class ContractModRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'contract', 'requested_by_username', 'status', 'created_at')


@admin.register(ContractFieldEffect)
class ContractFieldEffectAdmin(admin.ModelAdmin):
    list_display = ('id', 'contract', 'company', 'field_key', 'op', 'value_raw', 'round_no', 'created_at')

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
