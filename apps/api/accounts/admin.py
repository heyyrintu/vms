from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class TransportUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Transport workflow", {"fields": ("role", "vendor", "whatsapp_phone")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Transport workflow", {"fields": ("email", "whatsapp_phone", "role", "vendor")}),
    )
    list_display = UserAdmin.list_display + ("role", "whatsapp_phone")
