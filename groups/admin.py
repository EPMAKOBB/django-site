"""Admin configuration for groups app."""

from django.contrib import admin

from .models import Group, InvitationCode


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "teacher")
    filter_horizontal = ("students",)


@admin.register(InvitationCode)
class InvitationCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "group", "created_at", "used_by")
    list_filter = ("group",)
