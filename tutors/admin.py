from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import Tutor, Offering, AvailabilityRule, AvailabilityException, Booking
from .services import resolve, lock_teacher

class OfferingInline(admin.TabularInline):
    model = Offering
    extra = 1
class RuleInline(admin.TabularInline):
    model = AvailabilityRule
    extra = 0
class ExceptionInline(admin.TabularInline):
    model = AvailabilityException
    extra = 0

@admin.register(Tutor)
class TutorAdmin(admin.ModelAdmin):
    list_display = ['display_name','affiliation','status','accepting_students','booking_enabled']
    list_filter = ['status','affiliation','accepting_students','booking_enabled']
    search_fields = ['display_name','profile__user__username']
    prepopulated_fields = {'slug':('display_name',)}
    inlines = [OfferingInline, RuleInline, ExceptionInline]
    fieldsets = [
        ('Анкета', {'fields':['profile','display_name','slug','photo','summary','description','education','teaching_since','contacts']}),
        ('Публикация', {'fields':['affiliation','status','accepting_students','sort_order']}),
        ('Запись на занятия', {'fields':['booking_enabled','timezone','break_minutes','notice_hours','horizon_days','confirmation_hours']}),
    ]

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['tutor','student_name','start','status','expires_at']
    list_filter = ['status','tutor']
    search_fields = ['student_name','contact_name','contact_info']
    actions = ['confirm','reject','cancel']
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in Booking._meta.fields if field.name != 'price' or (obj and obj.status != Booking.Status.PENDING)]
    def save_model(self, request, obj, form, change):
        # Editing the agreed price must not overwrite a concurrent confirmation.
        with transaction.atomic():
            lock_teacher(obj.tutor)
            current = Booking.objects.select_for_update().get(pk=obj.pk)
            if current.status == Booking.Status.PENDING:
                current.price = obj.price
                current.save(update_fields=['price'])
            else:
                self.message_user(request, 'Запись уже обработана; цена сохранена без изменений.', messages.WARNING)
    def apply_action(self, request, queryset, action):
        for booking in queryset:
            try:
                resolve(booking_id=booking.pk, actor=request.user, action=action)
            except ValidationError as error:
                self.message_user(request, '; '.join(error.messages), messages.ERROR)
    @admin.action(description='Подтвердить и создать занятие')
    def confirm(self, request, queryset):
        self.apply_action(request, queryset, 'confirm')
    @admin.action(description='Отклонить')
    def reject(self, request, queryset):
        self.apply_action(request, queryset, 'reject')
    @admin.action(description='Отменить')
    def cancel(self, request, queryset):
        self.apply_action(request, queryset, 'cancel')
