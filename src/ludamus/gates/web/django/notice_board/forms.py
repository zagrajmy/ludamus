from typing import Any

from django import forms
from django.utils.translation import gettext as _gettext
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.forms import cover_image_field, validate_uploaded_image


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
            "Listed for everyone on the encounters page and the timeline. "
            "Anyone with the link can always view it."
        ),
    )
    header_image = cover_image_field()

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
                    "end_time", _gettext("End time must be after start time.")
                )
        return cleaned
