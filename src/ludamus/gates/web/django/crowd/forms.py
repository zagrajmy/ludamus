from django import forms
from django.utils.translation import gettext_lazy as _


class PartyNameForm(forms.Form):
    name = forms.CharField(label=_("Party name"), max_length=255)


class PartyInviteForm(forms.Form):
    email = forms.EmailField(
        label=_("Email"),
        help_text=_("The invited person needs a Ludamus account with this email."),
    )
