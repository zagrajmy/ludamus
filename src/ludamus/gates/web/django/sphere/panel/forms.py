"""Forms for the sphere panel."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.forms import logo_field
from ludamus.pacts.encounter import EncountersPolicy


class AnnouncementForm(forms.Form):
    title = forms.CharField(label=_("Title"), max_length=255, strip=True)
    content = forms.CharField(
        label=_("Content"), max_length=50000, widget=forms.Textarea(attrs={"rows": 8})
    )
    is_published = forms.BooleanField(
        label=_("Published"),
        required=False,
        initial=True,
        help_text=_("Visible on the public page. Uncheck to keep it as a draft."),
    )


class ConnectionForm(forms.Form):
    """Form for creating/editing import connections."""

    display_name = forms.CharField(label=_("Display name"), max_length=255, strip=True)
    replace_secret = forms.BooleanField(label=_("Replace secret"), required=False)
    secret = forms.CharField(
        label=_("Secret"),
        widget=forms.Textarea(attrs={"rows": 8, "autocomplete": "off"}),
        required=False,
        help_text=_("Paste the API connection secret."),
    )

    def __init__(self, *args: Any, is_create: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.is_create = is_create
        if is_create:
            # On create there's nothing to "replace" — the secret is mandatory.
            self.fields["secret"].required = True

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        if (
            not self.is_create
            and cleaned.get("replace_secret")
            and not (cleaned.get("secret") or "").strip()
        ):
            self.add_error("secret", _("Secret is required when replacing."))
        return cleaned


class SphereSettingsForm(forms.Form):
    """Form for sphere-wide settings."""

    allow_facilitator_session_edit = forms.BooleanField(
        required=False,
        label=_("Allow facilitators to edit their own sessions"),
        help_text=_("Default for the whole sphere. Events can override this setting."),
    )
    require_session_space = forms.BooleanField(
        required=False,
        label=_("Require a space for every scheduled session"),
        help_text=_(
            "Default for the whole sphere; events can override it. Turn off for "
            "meetups that only need a time."
        ),
    )
    parley_enabled = forms.BooleanField(
        required=False,
        label=_("Enable chat"),
        help_text=_(
            "Signed-in people can talk in a room for the whole sphere and in the "
            "rooms of the programme points they take part in."
        ),
    )
    event_cover_buttons_at_bottom = forms.BooleanField(
        required=False,
        label=_("Place event cover buttons at the bottom right"),
        help_text=_(
            "Shows print and venue map buttons in a horizontal row at the bottom "
            "right of event covers."
        ),
    )
    encounters_policy = forms.ChoiceField(
        choices=[
            (EncountersPolicy.NONE.value, _("Nobody (encounters are off here)")),
            (EncountersPolicy.MANAGERS.value, _("Sphere managers only")),
            (EncountersPolicy.EVERYONE.value, _("Everyone")),
        ],
        widget=forms.RadioSelect,
        label=_("Who may organize encounters"),
        help_text=_(
            "Encounters are small meetups organized by hand. Public ones are "
            "listed for everyone on the events page."
        ),
    )
    confirmed_encounters_disable = forms.BooleanField(
        required=False, widget=forms.HiddenInput
    )
    logo = logo_field()
