"""Forms for the groups app."""

from django import forms


class InvitationCodeForm(forms.Form):
    """Form for a student to join a group using an invitation code."""

    code = forms.CharField(label="Invitation code", max_length=12)
