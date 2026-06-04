from typing import Any

from django import forms
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

from ludamus.gates.web.django.forms import (
    COVER_IMAGE_ACCEPT,
    COVER_IMAGE_HELP_TEXT,
    validate_uploaded_image,
)


class EncounterForm(forms.Form):
    title = forms.CharField(label=_lazy("Title"), max_length=255)
    description = forms.CharField(
        label=_lazy("Description"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_lazy("Supports Markdown formatting."),
    )
    game = forms.CharField(label=_lazy("Game"), max_length=255, required=False)
    start_time = forms.DateTimeField(
        label=_lazy("Start time"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    end_time = forms.DateTimeField(
        label=_lazy("End time"),
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    place = forms.CharField(label=_lazy("Place"), max_length=255, required=False)
    max_participants = forms.IntegerField(
        label=_lazy("Max participants"), min_value=0, initial=0, required=False
    )
    header_image = forms.ImageField(
        label=_lazy("Cover image"),
        required=False,
        help_text=COVER_IMAGE_HELP_TEXT,
        widget=forms.ClearableFileInput(attrs={"accept": COVER_IMAGE_ACCEPT}),
    )

    def clean_header_image(self) -> object:
        image = self.cleaned_data.get("header_image")
        validate_uploaded_image(image)
        return image

    def clean(self) -> dict[str, Any] | None:
        if cleaned := super().clean():
            start = cleaned.get("start_time")
            end = cleaned.get("end_time")
            if start and end and end <= start:
                self.add_error("end_time", _("End time must be after start time."))
        return cleaned
