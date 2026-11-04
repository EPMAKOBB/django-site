from zoneinfo import available_timezones
from django import forms
from .models import Tutor, AvailabilityRule, AvailabilityException

TIMEZONES = [(name, name) for name in sorted(available_timezones())]

class SlotForm(forms.Form):
    offering = forms.TypedChoiceField(label='Направление', coerce=int)
    timezone = forms.ChoiceField(label='Ваш часовой пояс', choices=TIMEZONES, initial='Europe/Moscow')

class BookingForm(forms.Form):
    start = forms.DateTimeField(widget=forms.HiddenInput)
    student_name = forms.CharField(label='Имя ученика', max_length=160)
    contact_name = forms.CharField(label='Имя контактного лица', max_length=160)
    contact_info = forms.CharField(label='Телефон, Telegram или почта', max_length=255)
    consent = forms.BooleanField(label='Согласен передать эти контакты выбранному преподавателю для организации занятия')
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Не удалось отправить запись.')
        return ''

class CalendarSettingsForm(forms.ModelForm):
    class Meta:
        model = Tutor
        fields = ['booking_enabled', 'timezone', 'break_minutes', 'notice_hours', 'horizon_days', 'confirmation_hours']
        widgets = {'timezone': forms.Select(choices=TIMEZONES)}

RuleFormSet = forms.inlineformset_factory(Tutor, AvailabilityRule, fields=['weekday', 'start_time', 'end_time'], extra=1, max_num=30, validate_max=True, widgets={'start_time': forms.TimeInput(format='%H:%M', attrs={'type':'time'}), 'end_time': forms.TimeInput(format='%H:%M', attrs={'type':'time'})})
ExceptionFormSet = forms.inlineformset_factory(Tutor, AvailabilityException, fields=['date', 'closed', 'start_time', 'end_time'], extra=1, max_num=100, validate_max=True, widgets={'date': forms.DateInput(format='%Y-%m-%d', attrs={'type':'date'}), 'start_time': forms.TimeInput(format='%H:%M', attrs={'type':'time'}), 'end_time': forms.TimeInput(format='%H:%M', attrs={'type':'time'})})
