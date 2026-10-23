from typing import cast

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.pacts.crowd import AgeBand, UserData, UserType

# Not an AgeBand: nobody under the minimum age holds an account, so this answer
# is never stored, only acted on.
_UNDER_MIN_AGE = "under_13"


class AgeRangeForm(forms.Form):
    age_band = forms.ChoiceField(
        label=_("Age range"),
        choices=[
            (AgeBand.SIXTEEN_PLUS, _("16 or older")),
            (AgeBand.THIRTEEN_TO_FIFTEEN, _("13–15")),
            (_UNDER_MIN_AGE, _("Under 13")),
        ],
        widget=forms.RadioSelect,
    )

    def clean_age_band(self) -> AgeBand | None:
        """Return the declared range, or None for an answer below the minimum age."""
        answer = self.cleaned_data["age_band"]
        return None if answer == _UNDER_MIN_AGE else AgeBand(answer)


class SignupAgeForm(AgeRangeForm):
    confirmation_token = forms.CharField(widget=forms.HiddenInput())


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
        # A copy: callers pop and add keys before handing it to a service, and
        # the form still has to render its own cleaned_data on a re-display.
        return cast("UserData", dict(self.cleaned_data))


class UserForm(BaseUserForm):
    user_type = forms.CharField(initial=UserType.ACTIVE, widget=forms.HiddenInput())
    email = forms.EmailField(label=_("email address"), required=False)
    discord_username = forms.CharField(
        label=_("Discord username"),
        required=False,
        max_length=150,
        help_text=_("Your Discord username for session coordination"),
    )


class CompanionForm(BaseUserForm):
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
