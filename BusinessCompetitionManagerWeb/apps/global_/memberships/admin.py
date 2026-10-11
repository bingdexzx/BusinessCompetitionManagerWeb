from django.contrib import admin

from .models import CompetitionMembership


@admin.register(CompetitionMembership)
class CompetitionMembershipAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'competition', 'identity', 'managed_companies', 'is_active', 'created_at')
    list_filter = ('identity', 'is_active')
