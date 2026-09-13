from django.contrib import admin

from .models import (
    ContactPerson,
    StudentAccountInvite,
    StudentContact,
    StudentRecord,
    StudentStatusEvent,
)


class StudentContactInline(admin.TabularInline):
    model = StudentContact
    extra = 0
    autocomplete_fields = ("contact",)


class StudentStatusEventInline(admin.TabularInline):
    model = StudentStatusEvent
    extra = 0
    can_delete = False
    readonly_fields = ("from_status", "to_status", "changed_by", "reason", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(StudentRecord)
class StudentRecordAdmin(admin.ModelAdmin):
    list_display = ("full_name", "status", "grade", "city", "user", "updated_at")
    list_filter = ("status", "grade", "timezone")
    search_fields = ("full_name", "user__username", "contact_links__contact__phone")
    autocomplete_fields = ("user", "created_by")
    readonly_fields = ("public_id", "created_at", "updated_at")
    inlines = (StudentContactInline, StudentStatusEventInline)


@admin.register(ContactPerson)
class ContactPersonAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "email", "telegram_username")
    search_fields = ("full_name", "phone", "email", "telegram_username")
    autocomplete_fields = ("user",)


@admin.register(StudentContact)
class StudentContactAdmin(admin.ModelAdmin):
    list_display = ("student", "contact", "relationship", "is_primary", "is_payer", "is_active")
    list_filter = ("relationship", "is_primary", "is_payer", "is_active")
    autocomplete_fields = ("student", "contact")


@admin.register(StudentAccountInvite)
class StudentAccountInviteAdmin(admin.ModelAdmin):
    list_display = ("student", "created_by", "expires_at", "used_at", "revoked_at")
    readonly_fields = ("token_hash", "created_at", "used_at")
    autocomplete_fields = ("student", "created_by")


@admin.register(StudentStatusEvent)
class StudentStatusEventAdmin(admin.ModelAdmin):
    list_display = ("student", "from_status", "to_status", "changed_by", "created_at")
    list_filter = ("to_status",)
    readonly_fields = ("student", "from_status", "to_status", "changed_by", "reason", "created_at")

    def has_add_permission(self, request):
        return False
