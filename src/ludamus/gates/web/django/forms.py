"""Django forms for panel views."""

from typing import ClassVar

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _gettext
from django.utils.translation import gettext_lazy as _

from ludamus.adapters.db.django.models import AccreditationType

_DATETIME_LOCAL_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]
# Image-upload invariants (business rules, not gate trivia): every cover/header
# upload across the app is held to these same limits via validate_uploaded_image.
MAX_IMAGE_SIZE = 8 * 1024 * 1024
# A small (≤8 MB) file can still decode to a huge bitmap; cap pixel count to
# bound memory (decompression-bomb guard). 24 MP comfortably fits any cover.
MAX_IMAGE_PIXELS = 24_000_000
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "AVIF"})
COVER_IMAGE_ACCEPT = "image/jpeg,image/png,image/webp,image/avif"
COVER_IMAGE_HELP_TEXT = _("Max 8 MB. JPG, PNG, WebP, or AVIF.")


def validate_uploaded_image_size(image: object) -> None:
    size = getattr(image, "size", 0)
    if isinstance(size, int) and size > MAX_IMAGE_SIZE:
        raise ValidationError(_gettext("Image too large. Maximum size is 8 MB."))


def validate_uploaded_image_format(image: object) -> None:
    # Django's ImageField populates `image.image` (a PIL Image with `.format`)
    # during clean. We trust the detected format over user-supplied
    # content_type or filename extension.
    pil_image = getattr(image, "image", None)
    if getattr(pil_image, "format", None) not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError(
            _gettext("Unsupported image format. Use JPG, PNG, WebP, or AVIF.")
        )
    width = getattr(pil_image, "width", 0)
    height = getattr(pil_image, "height", 0)
    if width * height > MAX_IMAGE_PIXELS:
        raise ValidationError(_gettext("Image dimensions are too large."))


def validate_uploaded_image(image: object) -> None:
    # Single entry point shared by every cover/header upload form so the size +
    # format guarantees can't drift apart across forms.
    if image:
        validate_uploaded_image_size(image)
        validate_uploaded_image_format(image)


def cover_image_field() -> forms.ImageField:
    # Shared definition so every cover/header upload field stays identical
    # (label, limits, accepted types) without copy-pasting the declaration.
    return forms.ImageField(
        label=_("Cover image"),
        required=False,
        help_text=COVER_IMAGE_HELP_TEXT,
        widget=forms.ClearableFileInput(attrs={"accept": COVER_IMAGE_ACCEPT}),
    )


def _logo_field() -> forms.ImageField:
    # Reuses the shared image validators (format + decompression-bomb guard);
    # the printable-schedule logo only differs in label and accepted types.
    return forms.ImageField(
        required=False,
        label=_("Logo"),
        help_text=_(
            "Shown on the printable schedule. Max 8 MB. JPG, PNG, WebP, or AVIF."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": COVER_IMAGE_ACCEPT}),
    )


def _datetime_local_widget() -> forms.DateTimeInput:
    return forms.DateTimeInput(
        attrs={
            "type": "datetime-local",
            "class": (
                "w-full border border-border rounded-lg px-4 py-2"
                " focus:outline-none focus:ring-2 focus:ring-primary"
            ),
        },
        format="%Y-%m-%dT%H:%M",
    )


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
        max_length=50, error_messages={"required": _("Event slug is required.")}
    )
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    cover_image = cover_image_field()
    logo = _logo_field()
    start_time = forms.DateTimeField(
        widget=_datetime_local_widget(),
        input_formats=_DATETIME_LOCAL_FORMATS,
        error_messages={"required": _("Start time is required.")},
    )
    end_time = forms.DateTimeField(
        widget=_datetime_local_widget(),
        input_formats=_DATETIME_LOCAL_FORMATS,
        error_messages={"required": _("End time is required.")},
    )
    publication_time = forms.DateTimeField(
        required=False,
        widget=_datetime_local_widget(),
        input_formats=_DATETIME_LOCAL_FORMATS,
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
    auto_confirm_sessions = forms.BooleanField(
        required=False,
        label=_("Automatically confirm program items once scheduled"),
        help_text=_(
            "When on, a program item is confirmed the moment it is placed on "
            "the schedule. Turn off to confirm items manually."
        ),
    )

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image

    def clean_logo(self) -> object:
        image = self.cleaned_data.get("logo")
        validate_uploaded_image(image)
        return image


class SphereSettingsForm(forms.Form):
    """Form for sphere-wide settings."""

    allow_facilitator_session_edit = forms.BooleanField(
        required=False,
        label=_("Allow facilitators to edit their own sessions"),
        help_text=_("Default for the whole sphere. Events can override this setting."),
    )
    logo = _logo_field()

    def clean_logo(self) -> object:
        image = self.cleaned_data.get("logo")
        validate_uploaded_image(image)
        return image


class ProposalSettingsForm(forms.Form):
    """Form for proposal settings (description, dates, apply-to-categories)."""

    proposal_description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    proposal_start_time = forms.DateTimeField(
        required=False,
        widget=_datetime_local_widget(),
        input_formats=_DATETIME_LOCAL_FORMATS,
    )
    proposal_end_time = forms.DateTimeField(
        required=False,
        widget=_datetime_local_widget(),
        input_formats=_DATETIME_LOCAL_FORMATS,
    )
    apply_dates_to_categories = forms.BooleanField(required=False, initial=False)


class ProposalCategoryForm(forms.Form):
    """Form for creating/editing proposal categories."""

    name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Category name is too long (max 255 characters)."),
            "required": _("Category name is required."),
        },
    )
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    start_time = forms.DateTimeField(required=False)
    end_time = forms.DateTimeField(required=False)
    min_participants_limit = forms.IntegerField(required=False, min_value=0, initial=0)
    max_participants_limit = forms.IntegerField(required=False, min_value=0, initial=0)

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        min_limit = cleaned.get("min_participants_limit") or 0
        max_limit = cleaned.get("max_participants_limit") or 0
        if min_limit and max_limit and min_limit > max_limit:
            raise forms.ValidationError(
                _("Minimum participants limit cannot exceed maximum.")
            )
        return cleaned


class PersonalDataFieldForm(forms.Form):
    """Form for creating/editing personal data fields."""

    FIELD_TYPE_CHOICES: ClassVar = [
        ("text", _("Text")),
        ("select", _("Select")),
        ("checkbox", _("Checkbox")),
    ]

    name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Field name is too long (max 255 characters)."),
            "required": _("Field name is required."),
        },
    )
    question = forms.CharField(
        max_length=500,
        strip=True,
        error_messages={
            "max_length": _("Question text is too long (max 500 characters)."),
            "required": _("Question text is required."),
        },
    )
    field_type = forms.ChoiceField(
        choices=FIELD_TYPE_CHOICES, initial="text", required=False
    )
    options = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text=_("One option per line (for Select fields only)."),
    )
    is_multiple = forms.BooleanField(
        required=False,
        initial=False,
        help_text=_("Allow selecting multiple options (for Select fields only)."),
    )
    allow_custom = forms.BooleanField(
        required=False,
        initial=False,
        help_text=_("Allow entering custom values (for Select fields only)."),
    )
    max_length = forms.IntegerField(
        required=False,
        min_value=0,
        help_text=_(
            "Maximum number of characters allowed (0 = no limit)."
            " Applies to text fields and custom value inputs."
        ),
    )
    help_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=_(
            "Supports markdown (links, bold)."
            " Shown below the field in the proposal form."
        ),
    )
    is_public = forms.BooleanField(required=False, initial=False)


class SessionFieldForm(forms.Form):
    """Form for creating/editing session fields."""

    FIELD_TYPE_CHOICES: ClassVar = [
        ("text", _("Text")),
        ("select", _("Select")),
        ("checkbox", _("Checkbox")),
    ]

    name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Field name is too long (max 255 characters)."),
            "required": _("Field name is required."),
        },
    )
    question = forms.CharField(
        max_length=500,
        strip=True,
        error_messages={
            "max_length": _("Question text is too long (max 500 characters)."),
            "required": _("Question text is required."),
        },
    )
    field_type = forms.ChoiceField(
        choices=FIELD_TYPE_CHOICES, initial="text", required=False
    )
    options = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text=_("One option per line (for Select fields only)."),
    )
    is_multiple = forms.BooleanField(
        required=False,
        initial=False,
        help_text=_("Allow selecting multiple options (for Select fields only)."),
    )
    allow_custom = forms.BooleanField(
        required=False,
        initial=False,
        help_text=_("Allow entering custom values (for Select fields only)."),
    )
    max_length = forms.IntegerField(
        required=False,
        min_value=0,
        help_text=_(
            "Maximum number of characters allowed (0 = no limit)."
            " Applies to text fields and custom value inputs."
        ),
    )
    help_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=_(
            "Supports markdown (links, bold)."
            " Shown below the field in the proposal form."
        ),
    )
    icon = forms.CharField(max_length=50, required=False)
    is_public = forms.BooleanField(required=False, initial=False)


class VenueForm(forms.Form):
    """Form for creating/editing venues."""

    name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Venue name is too long (max 255 characters)."),
            "required": _("Venue name is required."),
        },
    )
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class VenueDuplicateForm(forms.Form):
    """Form for duplicating a venue within the same event."""

    name = forms.CharField(
        max_length=255,
        strip=True,
        label=_("New Venue Name"),
        error_messages={
            "max_length": _("Venue name is too long (max 255 characters)."),
            "required": _("Venue name is required."),
        },
    )


def create_venue_copy_form(events: list[tuple[int, str]]) -> type[forms.Form]:
    """Create a form for copying a venue to another event.

    Args:
        events: List of (event_id, event_name) tuples for target event choices.

    Returns:
        A form class with the target_event field configured.
    """
    target_event_field = forms.ChoiceField(
        label=_("Target Event"),
        choices=events,
        error_messages={
            "required": _("Please select a target event."),
            "invalid_choice": _("Invalid event selection."),
        },
    )

    return type("VenueCopyForm", (forms.Form,), {"target_event": target_event_field})


class AreaForm(forms.Form):
    """Form for creating/editing areas within a venue."""

    name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Area name is too long (max 255 characters)."),
            "required": _("Area name is required."),
        },
    )
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )


class TimeSlotForm(forms.Form):
    """Form for creating/editing time slots."""

    date = forms.DateField(
        error_messages={
            "required": _("Date is required."),
            "invalid": _("Enter a valid date."),
        }
    )
    end_date = forms.DateField(
        error_messages={
            "required": _("End date is required."),
            "invalid": _("Enter a valid date."),
        }
    )
    start_time = forms.TimeField(
        error_messages={
            "required": _("Start time is required."),
            "invalid": _("Enter a valid time."),
        }
    )
    end_time = forms.TimeField(
        error_messages={
            "required": _("End time is required."),
            "invalid": _("Enter a valid time."),
        }
    )


class SpaceForm(forms.Form):
    """Form for creating/editing spaces within an area."""

    name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Space name is too long (max 255 characters)."),
            "required": _("Space name is required."),
        },
    )
    capacity = forms.IntegerField(
        required=False,
        min_value=1,
        error_messages={"min_value": _("Capacity must be at least 1.")},
    )


class TrackForm(forms.Form):
    """Form for creating/editing tracks."""

    name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Track name is too long (max 255 characters)."),
            "required": _("Track name is required."),
        },
    )
    is_public = forms.BooleanField(
        required=False,
        initial=True,
        help_text=_("Public tracks are shown to proposers in the submission wizard."),
    )


class SessionEditForm(forms.Form):
    """Form for editing session fields by an organizer."""

    title = forms.CharField(
        max_length=255, strip=True, error_messages={"required": _("Title is required.")}
    )
    display_name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={"required": _("Display name is required.")},
    )
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 5})
    )
    requirements = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    needs = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    contact_email = forms.EmailField(required=False)
    participants_limit = forms.IntegerField(required=False, min_value=0)
    min_age = forms.IntegerField(required=False, min_value=0)
    duration = forms.CharField(required=False)
    cover_image = cover_image_field()

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image


def create_proposal_form(categories: list[tuple[int, str]]) -> type[SessionEditForm]:
    category_field = forms.ChoiceField(
        choices=[("", _("— Select category —")), *categories],
        error_messages={
            "required": _("Please select a category."),
            "invalid_choice": _("Invalid category selection."),
        },
    )
    return type(
        "ProposalCreateForm", (SessionEditForm,), {"category_id": category_field}
    )


class FacilitatorForm(forms.Form):
    """Form for creating/editing a facilitator."""

    display_name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Display name is too long (max 255 characters)."),
            "required": _("Display name is required."),
        },
    )
    accreditation_type = forms.ChoiceField(
        choices=AccreditationType.choices,
        initial=AccreditationType.NONE,
        required=False,
        label=_("Accreditation type"),
    )

    def clean_accreditation_type(self) -> str:
        return self.cleaned_data.get("accreditation_type") or AccreditationType.NONE
