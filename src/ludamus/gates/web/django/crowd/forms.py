from typing import cast

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.pacts.crowd import UserData, UserType


class BaseUserForm(forms.Form):
    name = forms.CharField(
        label=_("Display name"),
        help_text=_(
            "Your public display name that others will see. This can be a nickname "
            "and does not need to be your legal name."
        ),
    )

    @property
    def user_data(self) -> UserData:
        return cast("UserData", self.cleaned_data)


class UserForm(BaseUserForm):
    user_type = forms.CharField(initial=UserType.ACTIVE, widget=forms.HiddenInput())
    email = forms.EmailField(label=_("email address"), required=False)
    discord_username = forms.CharField(
        label=_("Discord username"),
        required=False,
        max_length=150,
        help_text=_("Your Discord username for session coordination"),
    )


class ConnectedUserForm(BaseUserForm):
    user_type = forms.CharField(
        initial=UserType.CONNECTED.value, widget=forms.HiddenInput()
    )


class PartyNameForm(forms.Form):
    name = forms.CharField(label=_("Party name"), max_length=255)


class PartyInviteForm(forms.Form):
    identifier = forms.CharField(
        label=_("Email or Discord username"),
        help_text=_(
            "Their account email, or the Discord username they signed up with. "
            "They need a Zagrajmy account."
        ),
    )


class PartyCompanionForm(forms.Form):
    display_name = forms.CharField(
        label=_("Companion display name"),
        help_text=_("Enter one of your companions exactly as they are named."),
        max_length=255,
    )
