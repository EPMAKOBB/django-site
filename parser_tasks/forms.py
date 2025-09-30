from django import forms

from .services import DEFAULT_SOURCE_URL


class ParserRunForm(forms.Form):
    source_url = forms.URLField(
        label="Ссылка на вариант",
        help_text=(
            "Укажите ссылку на вариант ЕГЭ с сайта inf-ege.sdamgia.ru. "
            "По умолчанию используется рекомендованный вариант."
        ),
        initial=DEFAULT_SOURCE_URL,
        required=True,
    )
