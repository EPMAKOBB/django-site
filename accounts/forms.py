from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm as DjangoPasswordChangeForm,
)
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class SignupForm(forms.Form):
    contact = forms.CharField(
        label=_("Контактные данные"),
        max_length=255,
        help_text=_(
            "Укажите email или телефон — они понадобятся для восстановления аккаунта"
        ),
    )
    username = forms.CharField(label=_("Логин"), max_length=150)
    password = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(_("Этот логин уже занят"))
        return username

    def save(self, commit: bool = True):
        user = User(username=self.cleaned_data["username"], email=self.cleaned_data["contact"])
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    pass


class UsernameChangeForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username",)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Этот логин уже занят"))
        return username


class UserUpdateForm(forms.ModelForm):
    """Form for updating basic user information."""

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")
        labels = {
            "username": _("Логин"),
            "first_name": _("Имя"),
            "last_name": _("Фамилия"),
            "email": _("Электронная почта"),
        }
        error_messages = {
            "username": {"required": _("Укажите логин")},
            "first_name": {"required": _("Укажите имя")},
            "last_name": {"required": _("Укажите фамилию")},
            "email": {
                "required": _("Укажите адрес электронной почты"),
                "invalid": _("Введите правильный адрес электронной почты"),
            },
        }

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Этот логин уже занят"))
        return username


class PasswordChangeForm(DjangoPasswordChangeForm):
    """Password change form with Russian field labels."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = _("Старый пароль")
        self.fields["new_password1"].label = _("Новый пароль")
        self.fields["new_password2"].label = _("Подтверждение нового пароля")
