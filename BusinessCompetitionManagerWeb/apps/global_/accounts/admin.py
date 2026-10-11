from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class GipfelUserAdmin(UserAdmin):
    list_display = ('id', 'username', 'email', 'display_name', 'school', 'is_superuser', 'is_active', 'token_version')
    list_filter = ('is_superuser', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Gipfel', {'fields': ('display_name', 'school', 'token_version')}),
    )
