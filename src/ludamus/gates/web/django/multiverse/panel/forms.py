"""Forms for the multiverse sphere panel."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _


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
