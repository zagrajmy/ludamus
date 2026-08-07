"""Forms for the multiverse sphere panel."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.forms import logo_field, validate_uploaded_logo


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


class GuildForm(forms.Form):
    """Create/edit a guild: its name and its mark."""

    name = forms.CharField(label=_("Guild name"), max_length=255, strip=True)
    logo = logo_field(
        help_text=_(
            "The mark shown beside members' names on programme cards. Square, "
            "one colour, no lettering — it renders at about 19 px. Max 8 MB. "
            "SVG, PNG, WebP, JPG, or AVIF."
        )
    )

    def clean_logo(self) -> object:
        logo = self.cleaned_data.get("logo")
        validate_uploaded_logo(logo)
        return logo


class GuildMemberForm(forms.Form):
    """Assign one presenter to a guild."""

    identifier = forms.CharField(
        label=_("Email or Discord username"),
        help_text=_(
            "Their account email, or the Discord username they signed up with. "
            "They need a Zagrajmy account."
        ),
    )
