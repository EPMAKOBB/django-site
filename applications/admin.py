from django.contrib import admin, messages
from django.db import transaction

from students.models import ContactPerson, StudentContact, StudentRecord

from .models import Application, ApplicationStudent


class ApplicationStudentInline(admin.TabularInline):
    model = ApplicationStudent
    extra = 0
    autocomplete_fields = ("student", "created_by")


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "contact_name",
        "student_name",
        "status",
        "assigned_to",
        "next_action_at",
        "created_at",
    )
    list_filter = ("grade", "subjects", "status", "assigned_to")
    search_fields = ("contact_name", "student_name", "contact_info")
    autocomplete_fields = ("contact_person", "assigned_to")
    filter_horizontal = ("subjects",)
    inlines = (ApplicationStudentInline,)
    actions = ("create_student_cards",)

    @admin.action(description="Создать карточки учеников из выбранных заявок")
    def create_student_cards(self, request, queryset):
        created_count = 0
        with transaction.atomic():
            for application in queryset.prefetch_related("student_links"):
                if application.student_links.exists():
                    continue
                student = StudentRecord.objects.create(
                    full_name=application.student_name or application.contact_name,
                    grade=application.grade,
                    status=StudentRecord.Status.LEAD,
                    created_by=request.user,
                )
                contact = ContactPerson.objects.create(
                    full_name=application.contact_name,
                    phone=application.contact_info,
                )
                StudentContact.objects.create(
                    student=student,
                    contact=contact,
                    relationship=(
                        StudentContact.Relationship.SELF
                        if not application.student_name
                        or application.student_name.strip() == application.contact_name.strip()
                        else StudentContact.Relationship.GUARDIAN
                    ),
                    is_primary=True,
                    is_payer=True,
                )
                ApplicationStudent.objects.create(
                    application=application,
                    student=student,
                    created_by=request.user,
                )
                application.contact_person = contact
                application.save(update_fields=("contact_person",))
                created_count += 1
        self.message_user(
            request,
            f"Создано карточек учеников: {created_count}",
            level=messages.SUCCESS,
        )


@admin.register(ApplicationStudent)
class ApplicationStudentAdmin(admin.ModelAdmin):
    list_display = ("application", "student", "is_primary", "created_at")
    autocomplete_fields = ("application", "student", "created_by")
