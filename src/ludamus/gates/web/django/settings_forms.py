"""Settings forms: an event's and its sphere's."""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from ludamus.gates.uploads import validate_uploaded_image
from ludamus.gates.web.django.forms import (
    DATETIME_LOCAL_FORMATS,
    MAX_ADDRESS_LINES,
    MarkdownTextarea,
    cover_image_field,
    datetime_local_widget,
    logo_field,
)
from ludamus.pacts.event import EventVisibility


class EventSettingsForm(forms.Form):
    """Form for event settings."""

    name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Event name is too long (max 255 characters)."),
            "required": _("Event name is required."),
        },
    )
    slug = forms.SlugField(
        label=_("Slug"),
        max_length=50,
        help_text=_("URL identifier for this event. Must be unique."),
        error_messages={"required": _("Event slug is required.")},
    )
    description = forms.CharField(
        label=_("Description"),
        required=False,
        widget=MarkdownTextarea(published=True, attrs={"rows": 3}),
        help_text=_("Aim for about 230 characters."),
    )
    address = forms.CharField(
        max_length=255,
        required=False,
        strip=True,
        label=_("Address"),
        help_text=_("Venue address, two lines at most. Shown with a map link."),
        widget=forms.Textarea(attrs={"rows": MAX_ADDRESS_LINES}),
    )

    def clean_address(self) -> str:
        lines = str(self.cleaned_data.get("address") or "").splitlines()
        kept = [stripped for line in lines if (stripped := line.strip())]
        if len(kept) > MAX_ADDRESS_LINES:
            raise ValidationError(gettext("An address can have at most two lines."))
        return "\n".join(kept)

    cover_image = cover_image_field(crop="top-and-bottom")
    logo = logo_field()
    start_time = forms.DateTimeField(
        label=_("Start time"),
        widget=datetime_local_widget(),
        input_formats=DATETIME_LOCAL_FORMATS,
        error_messages={"required": _("Start time is required.")},
    )
    end_time = forms.DateTimeField(
        label=_("End time"),
        widget=datetime_local_widget(),
        input_formats=DATETIME_LOCAL_FORMATS,
        error_messages={"required": _("End time is required.")},
    )
    visibility = forms.ChoiceField(
        choices=[
            (
                EventVisibility.PUBLIC.value,
                _(
                    "Public: listed and announced to followers from its "
                    "publication time"
                ),
            ),
            (
                EventVisibility.UNLISTED.value,
                _(
                    "Link only: anyone with the link can open it now; never "
                    "listed or announced"
                ),
            ),
        ],
        initial=EventVisibility.PUBLIC.value,
        widget=forms.RadioSelect,
        label=_("Who can see the event"),
    )
    publication_time = forms.DateTimeField(
        required=False,
        widget=datetime_local_widget(),
        input_formats=DATETIME_LOCAL_FORMATS,
        label=_("Publication time"),
        help_text=_(
            "For a public event: when it appears in event lists and followers "
            "are notified. Leave empty to keep it hidden."
        ),
    )
    allow_facilitator_session_edit = forms.ChoiceField(
        required=False,
        choices=[
            ("", _("Use sphere default")),
            ("true", _("Allow")),
            ("false", _("Disallow")),
        ],
        label=_("Facilitators editing their own sessions"),
    )
    require_session_space = forms.ChoiceField(
        required=False,
        choices=[
            ("", _("Use sphere default")),
            ("true", _("Required")),
            ("false", _("Optional")),
        ],
        label=_("A space for every scheduled session"),
        help_text=_(
            "Optional suits a meetup that only needs a time: sessions can be "
            "placed without a room."
        ),
    )
    auto_confirm_sessions = forms.BooleanField(
        required=False,
        label=_("Automatically confirm program items once scheduled"),
        help_text=_(
            "When on, a program item is confirmed the moment it is placed on "
            "the schedule. Turn off to confirm items manually."
        ),
    )
    use_session_cover_placeholders = forms.BooleanField(
        required=False,
        label=_("Use placeholder images for sessions without a cover image"),
        help_text=_(
            "When off, sessions without uploaded images are shown as text-only cards."
        ),
    )
    use_participants_label = forms.BooleanField(
        required=False,
        label=_('Label the attendee count "Participants" instead of "Players"'),
        help_text=_(
            "Turn on for non-gaming events so the public page counts participants "
            "rather than players."
        ),
    )

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image
