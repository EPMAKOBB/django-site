from django.contrib import admin

from .models import ParserRun


@admin.register(ParserRun)
class ParserRunAdmin(admin.ModelAdmin):
    list_display = ("created_at", "status", "tasks_count", "source_url")
    list_filter = ("status",)
    search_fields = ("source_url", "details")
    date_hierarchy = "created_at"
