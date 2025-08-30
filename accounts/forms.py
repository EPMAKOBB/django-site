from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

User = get_user_model()


class SignupForm(forms.Form):
    contact = forms.CharField(label="Контактные данные", max_length=255)
    username = forms.CharField(label="Логин", max_length=150)
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Этот логин уже занят")
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
            raise forms.ValidationError("Этот логин уже занят")
        return username
