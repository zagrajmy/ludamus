import re
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from ludamus.gates.uploads import validate_uploaded_image
from ludamus.gates.web.django.forms import cover_image_field

# NOTE: each address gets mail from our domain; the cap keeps one encounter
# from turning the form into a bulk mailer.
MAX_INVITEES = 50
_ADDRESS_SEPARATORS = re.compile(r"[\s,;]+")


class EncounterForm(forms.Form):
    title = forms.CharField(label=_("Title"), max_length=255)
    description = forms.CharField(
        label=_("Description"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Supports Markdown formatting."),
    )
    game = forms.CharField(label=_("Game"), max_length=255, required=False)
    start_time = forms.DateTimeField(
        label=_("Start time"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    end_time = forms.DateTimeField(
        label=_("End time"),
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    place = forms.CharField(label=_("Place"), max_length=255, required=False)
    max_participants = forms.IntegerField(
        label=_("Max participants"), min_value=0, initial=0, required=False
    )
    is_public = forms.BooleanField(
        label=_("Public encounter"),
        required=False,
        help_text=_(
            "Listed for everyone on the events page. Anyone with the link can "
            "always view it."
        ),
    )
    header_image = cover_image_field(crop="top-and-bottom")
    invitees = forms.CharField(
        label=_("Invite by email"),
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "autocomplete": "off", "spellcheck": "false"}
        ),
        help_text=_(
            "Separate addresses with commas or new lines. Each person gets a "
            "calendar invite and can accept it from their calendar."
        ),
    )

    def clean_invitees(self) -> list[str]:
        raw = self.cleaned_data.get("invitees") or ""
        emails = list(
            dict.fromkeys(
                part.lower() for part in _ADDRESS_SEPARATORS.split(raw) if part
            )
        )
        invalid = []
        for email in emails:
            try:
                validate_email(email)
            except ValidationError:
                invalid.append(email)
        if invalid:
            raise ValidationError(
                gettext("These are not email addresses: %(addresses)s")
                % {"addresses": ", ".join(invalid)}
            )
        if len(emails) > MAX_INVITEES:
            raise ValidationError(
                gettext("Invite at most %(limit)d people to one encounter.")
                % {"limit": MAX_INVITEES}
            )
        return emails

    def clean_header_image(self) -> object:
        image = self.cleaned_data.get("header_image")
        validate_uploaded_image(image)
        return image

    def clean(self) -> dict[str, Any] | None:
        if cleaned := super().clean():
            start = cleaned.get("start_time")
            end = cleaned.get("end_time")
            if start and end and end <= start:
                self.add_error(
                    "end_time", gettext("End time must be after start time.")
                )
        return cleaned
