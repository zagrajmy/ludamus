"""Forms for the multiverse sphere panel."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _


class AnnouncementForm(forms.Form):
    title = forms.CharField(label=_("Title"), max_length=255, strip=True)
    content = forms.CharField(
        label=_("Content"), widget=forms.Textarea(attrs={"rows": 8})
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
