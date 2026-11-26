from typing import cast

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.pacts.user import (
    PROFILE_DISCORD_USERNAME_MAX_LENGTH,
    AgeBand,
    UserData,
    UserType,
    looks_like_email,
)

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
    name = forms.CharField(
        label=_("Display name"),
        max_length=255,
        required=False,
        help_text=_(
            "How others see you on sessions and your profile. "
            "A nickname is fine — not an email address."
        ),
    )
    confirmation_token = forms.CharField(widget=forms.HiddenInput())
    field_order = ("name", "age_band", "confirmation_token")

    def clean(self) -> None:
        super().clean()
        cleaned = self.cleaned_data
        # Under the minimum age the account is never activated, so a display
        # name is not collected. Eligible ages must pick one before we create
        # the account — otherwise Auth0's email-as-name leaks into public UI.
        if cleaned.get("age_band") is None:
            cleaned["name"] = ""
            return
        if not (name := str(cleaned.get("name") or "").strip()):
            self.add_error("name", _("Enter a display name."))
        elif looks_like_email(name):
            self.add_error("name", _("Enter a display name, not an email address."))
        else:
            cleaned["name"] = name


class BaseUserForm(forms.Form):
    name = forms.CharField(
        label=_("Display name"),
        help_text=_(
            "Your public display name that others will see. This can be a nickname "
            "and does not need to be your legal name."
        ),
    )

    def clean_name(self) -> str:
        name = str(self.cleaned_data["name"]).strip()
        if looks_like_email(name):
            raise forms.ValidationError(
                _("Enter a display name, not an email address.")
            )
        return name

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
        max_length=PROFILE_DISCORD_USERNAME_MAX_LENGTH,
        help_text=_("Your Discord username for session coordination"),
    )


class CompanionForm(BaseUserForm):
    user_type = forms.CharField(
        initial=UserType.CONNECTED.value, widget=forms.HiddenInput()
    )


class PartyNameForm(forms.Form):
    name = forms.CharField(label=_("Party name"), max_length=255)


class PartyEnrollsTogetherForm(forms.Form):
    enrolls_together = forms.TypedChoiceField(
        choices=[("True", "True"), ("False", "False")],
        coerce=lambda value: value == "True",
        widget=forms.HiddenInput(),
    )


class PartyCreateForm(PartyEnrollsTogetherForm, PartyNameForm):
    pass


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
