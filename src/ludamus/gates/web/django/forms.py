"""Django forms for panel views."""

from __future__ import annotations

import operator
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, cast

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _gettext
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.templatetags.cfp_tags import format_duration
from ludamus.pacts.discounts import DiscountKind
from ludamus.pacts.images import ALLOWED_IMAGE_FORMATS, IMAGE_ACCEPT
from ludamus.pacts.legacy import PromotionMode
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ludamus.pacts import (
        PersonalFieldRequirementDTO,
        ProposalCategoryDTO,
        SessionFieldRequirementDTO,
    )
    from ludamus.pacts.multiverse import ConnectionDTO

_DATETIME_LOCAL_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]
# Image-upload invariants (business rules, not gate trivia): every cover/header
# upload across the app is held to these same limits via validate_uploaded_image.
MAX_IMAGE_SIZE = 8 * 1024 * 1024
# A small (≤8 MB) file can still decode to a huge bitmap; cap pixel count to
# bound memory (decompression-bomb guard). 24 MP comfortably fits any cover.
MAX_IMAGE_PIXELS = 24_000_000
# Hand-written rather than joined from IMAGE_FORMATS: it is translated user copy,
# and a comma-joined list of MIME types reads nothing like a sentence.
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
        widget=forms.ClearableFileInput(attrs={"accept": IMAGE_ACCEPT}),
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
        widget=forms.ClearableFileInput(attrs={"accept": IMAGE_ACCEPT}),
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
    allow_anonymous_proposals = forms.BooleanField(required=False, initial=False)


class EnrollmentWindowForm(forms.Form):
    start_time = forms.DateTimeField(
        label=_("Enrollment opens"),
        widget=_datetime_local_widget(),
        input_formats=_DATETIME_LOCAL_FORMATS,
    )
    end_time = forms.DateTimeField(
        label=_("Enrollment closes"),
        widget=_datetime_local_widget(),
        input_formats=_DATETIME_LOCAL_FORMATS,
    )
    percentage_slots = forms.IntegerField(
        label=_("Seats available during this window"),
        min_value=1,
        max_value=100,
        initial=100,
        help_text=_("Percentage of each session's capacity available for enrollment."),
    )
    max_waitlist_sessions = forms.IntegerField(
        label=_("Waiting-list limit per person"),
        min_value=0,
        initial=10,
        help_text=_("Use 0 to disable waiting lists during this window."),
    )
    banner_text = forms.CharField(
        label=_("Enrollment notice"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Shown to participants while this enrollment window is active."),
    )
    limit_to_end_time = forms.BooleanField(
        required=False,
        label=_("Apply only to sessions starting before enrollment closes"),
    )
    restrict_to_configured_users = forms.BooleanField(
        required=False,
        label=_("Require explicit enrollment access"),
        help_text=_(
            "Only people allowed by user, domain, or membership settings can enroll."
        ),
    )
    allow_anonymous_enrollment = forms.BooleanField(
        required=False, label=_("Allow enrollment without an account")
    )

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        if start_time and end_time and start_time >= end_time:
            raise forms.ValidationError(_("Enrollment must close after it opens."))
        return cleaned


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
    promotion_mode = forms.ChoiceField(
        required=False,
        initial=PromotionMode.AUTO.value,
        label=_("When a seat becomes available"),
        choices=(
            (PromotionMode.AUTO.value, _("Confirm the next person automatically")),
            (
                PromotionMode.OFFER_CLAIM.value,
                _("Hold the seat until the next person confirms"),
            ),
        ),
        widget=forms.RadioSelect,
    )
    offer_claim_window_minutes = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=10_080,
        initial=1_440,
        label=_("Time to confirm the seat"),
        help_text=_("Minutes before an unconfirmed seat goes to the next person."),
    )

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


class TimeSlotForm(forms.Form):
    """Form for creating/editing time slots."""

    date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={
            "required": _("Date is required."),
            "invalid": _("Enter a valid date."),
        },
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={
            "required": _("End date is required."),
            "invalid": _("Enter a valid date."),
        },
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}),
        error_messages={
            "required": _("Start time is required."),
            "invalid": _("Enter a valid time."),
        },
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}),
        error_messages={
            "required": _("End time is required."),
            "invalid": _("Enter a valid time."),
        },
    )


class SpaceForm(forms.Form):
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
        label=_("Capacity"),
        help_text=_(
            "Set the number of seats for a room that holds sessions, at any level."
            " Leave empty for a space that only groups other spaces."
        ),
        error_messages={"min_value": _("Capacity must be at least 1.")},
    )
    location = forms.CharField(
        required=False,
        max_length=255,
        label=_("Location"),
        help_text=_("Building address, room number, floor — structural details."),
    )
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )


class SpaceEditForm(SpaceForm):
    # Editing additionally allows reparenting; the view supplies the eligible
    # targets (no self, descendants, or session-holding spaces). The empty
    # choice ("Top level") moves the space to the root.
    def __init__(
        self, *args: Any, parent_choices: list[tuple[str, str]], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["parent"] = forms.ChoiceField(
            required=False,
            label=_("Parent"),
            help_text=_(
                "Move this space elsewhere, or choose Top level to flatten it."
            ),
            choices=parent_choices,
        )


def create_space_copy_form(events: list[tuple[int, str]]) -> type[forms.Form]:
    target_event_field = forms.ChoiceField(
        label=_("Target Event"),
        choices=events,
        error_messages={
            "required": _("Please select a target event."),
            "invalid_choice": _("Invalid event selection."),
        },
    )
    return type("SpaceCopyForm", (forms.Form,), {"target_event": target_event_field})


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


def build_field_from_requirement(
    fields: dict[str, forms.Field],
    field_key: str,
    req: PersonalFieldRequirementDTO | SessionFieldRequirementDTO,
) -> None:
    # Shared by the proposal wizard and the organizer panel so a category's
    # configured fields render identically in both. The label is the field's
    # question — the wording the proposer is actually asked — since the panel
    # renders these through tessera_field rather than hand-rolled labels.
    field_def = req.field
    label = field_def.question
    help_text = field_def.help_text

    if field_def.field_type == "select":
        raw_options = [(o.value, o.label, o.order) for o in field_def.options]
        raw_options.sort(key=operator.itemgetter(2, 1))
        choices = [("", "---")] + [(val, label) for val, label, _order in raw_options]

        if field_def.is_multiple:
            fields[field_key] = forms.MultipleChoiceField(
                label=label,
                help_text=help_text,
                choices=choices[1:],  # no blank for multi
                required=req.is_required,
                widget=forms.CheckboxSelectMultiple,
            )
        else:
            fields[field_key] = forms.ChoiceField(
                label=label,
                help_text=help_text,
                choices=choices,
                required=req.is_required,
            )

    elif field_def.field_type == "checkbox":
        # We can't make checkboxes required because it ENFORCES TRUE.
        fields[field_key] = forms.BooleanField(
            label=label, help_text=help_text, required=False
        )
    else:
        max_len = field_def.max_length if field_def.max_length > 0 else None
        fields[field_key] = forms.CharField(
            label=label,
            help_text=help_text,
            required=req.is_required,
            max_length=max_len,
        )

    # A checkbox has nothing to customise; every other type with allow_custom
    # gets the companion input the descriptors expect.
    if field_def.allow_custom and field_def.field_type != "checkbox":
        max_len = field_def.max_length if field_def.max_length > 0 else None
        fields[f"{field_key}_custom"] = forms.CharField(
            label=_("Or type a custom value"), required=False, max_length=max_len
        )


def field_descriptors(
    prefix: str,
    requirements: (
        Sequence[PersonalFieldRequirementDTO] | Sequence[SessionFieldRequirementDTO]
    ),
    form: forms.Form,
) -> list[dict[str, object]]:
    # Template-facing view of a category's fields: pairs each requirement with
    # its bound field so the wizard and the panel render them the same way.
    descriptors = []
    for req in requirements:
        field_key = f"{prefix}_{req.field.slug}"
        desc: dict[str, object] = {
            "key": field_key,
            "bound_field": form[field_key],
            "name": req.field.question,
            "slug": req.field.slug,
            "field_type": req.field.field_type,
            "help_text": req.field.help_text,
            "is_required": req.is_required,
            "is_multiple": req.field.is_multiple,
            "allow_custom": req.field.allow_custom,
            "max_length": req.field.max_length,
            "is_public": req.field.is_public,
            "icon": getattr(req.field, "icon", ""),
        }
        # Checkboxes get no companion input even when allow_custom is set.
        custom_key = f"{field_key}_custom"
        desc["custom_bound_field"] = (
            form[custom_key] if custom_key in form.fields else None
        )
        descriptors.append(desc)
    return descriptors


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
    contact_email = forms.EmailField(required=False)
    participants_limit = forms.IntegerField(required=False, min_value=0)
    min_age = forms.IntegerField(required=False, min_value=0)
    duration = forms.CharField(required=False)
    cover_image = cover_image_field()

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image


def _participants_limit_field(*, min_limit: int, max_limit: int) -> forms.IntegerField:
    # Stays optional (blank = no limit, as organizers expect) but honours the
    # category's configured bounds when one is set.
    kwargs: dict[str, Any] = {"required": False, "min_value": min_limit or 0}
    if max_limit:
        kwargs["max_value"] = max_limit
    return forms.IntegerField(**kwargs)


def create_proposal_form(
    categories: list[tuple[int, str]],
    *,
    facilitators: list[tuple[int, str]] | None = None,
    requirements: Sequence[SessionFieldRequirementDTO] = (),
    category: ProposalCategoryDTO | None = None,
) -> type[SessionEditForm]:
    attrs: dict[str, forms.Field] = {
        "category_id": forms.ChoiceField(
            choices=[("", _("— Select category —")), *categories],
            error_messages={
                "required": _("Please select a category."),
                "invalid_choice": _("Invalid category selection."),
            },
        )
    }
    # Create variant only: a required facilitator binding so a hand-added
    # proposal can never exist with zero facilitators. The edit view omits
    # this — it manages facilitators through its own inline list.
    if facilitators is not None:
        attrs["facilitator_ids"] = forms.MultipleChoiceField(
            choices=facilitators,
            error_messages={
                "required": _("Please select at least one facilitator."),
                "invalid_choice": _("Invalid facilitator selection."),
            },
        )

    if category and (
        category.min_participants_limit or category.max_participants_limit
    ):
        attrs["participants_limit"] = _participants_limit_field(
            min_limit=category.min_participants_limit,
            max_limit=category.max_participants_limit,
        )

    # A category with no configured durations keeps the inherited free-text
    # field, so organizers can still record one.
    if category and category.durations:
        attrs["duration"] = forms.ChoiceField(
            required=False,
            choices=[
                ("", "---"),
                *((d, format_duration(d)) for d in category.durations),
            ],
        )

    for req in requirements:
        build_field_from_requirement(attrs, f"session_{req.field.slug}", req)

    return type("ProposalCreateForm", (SessionEditForm,), attrs)


ACCREDITATION_TYPE_LABELS = {
    AccreditationType.NONE: _("None"),
    AccreditationType.STANDARD: _("Standard"),
    AccreditationType.GUEST: _("Guest"),
    AccreditationType.HONORARY: _("Honorary"),
}
ACCREDITATION_TYPE_CHOICES = [
    (t.value, ACCREDITATION_TYPE_LABELS[t]) for t in AccreditationType
]


class FacilitatorForm(forms.Form):
    """Form for creating a facilitator (display_name is required at creation)."""

    display_name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Display name is too long (max 255 characters)."),
            "required": _("Display name is required."),
        },
    )
    accreditation_type = forms.ChoiceField(
        choices=ACCREDITATION_TYPE_CHOICES,
        initial=AccreditationType.NONE,
        required=False,
        label=_("Accreditation type"),
    )

    def clean_accreditation_type(self) -> str:
        return self.cleaned_data.get("accreditation_type") or AccreditationType.NONE


class FacilitatorEditForm(forms.Form):
    # No display_name: it is a read-only cache (the canonical byline lives on
    # the session), so the panel edit form only touches accreditation_type.
    accreditation_type = forms.ChoiceField(
        choices=ACCREDITATION_TYPE_CHOICES,
        initial=AccreditationType.NONE,
        required=False,
        label=_("Accreditation type"),
    )
    internal_comment = forms.CharField(
        required=False,
        strip=True,
        widget=forms.Textarea(attrs={"rows": 3}),
        label=_("Internal comment"),
        help_text=_("Visible to organizers only."),
    )

    def clean_accreditation_type(self) -> str:
        return self.cleaned_data.get("accreditation_type") or AccreditationType.NONE


DISCOUNT_KIND_LABELS = {
    DiscountKind.PERCENT: _("Percent"),
    DiscountKind.AMOUNT: _("Amount"),
}


class DiscountForm(forms.Form):
    kind = forms.ChoiceField(
        choices=[(k.value, DISCOUNT_KIND_LABELS[k]) for k in DiscountKind],
        initial=DiscountKind.PERCENT,
        label=_("Kind"),
    )
    value = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
        label=_("Value"),
        widget=forms.NumberInput(attrs={"inputmode": "decimal"}),
        error_messages={
            "required": _("Value is required."),
            "min_value": _("Value must be greater than zero."),
        },
    )
    note = forms.CharField(
        max_length=255,
        strip=True,
        required=False,
        label=_("Note"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )


_SPREADSHEET_URL_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
_SPREADSHEET_ID_RE = re.compile(r"[A-Za-z0-9_-]+")


class DiscountExportForm(forms.Form):
    connection = forms.ChoiceField(label=_("Connection"))
    spreadsheet = forms.CharField(
        label=_("Google Sheets link"),
        max_length=500,
        strip=True,
        help_text=_("Paste the spreadsheet link (or its ID) from the address bar."),
    )

    def __init__(
        self, *args: Any, connections: Iterable[ConnectionDTO], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        connection_field = cast("forms.ChoiceField", self.fields["connection"])
        connection_field.choices = [
            (str(connection.pk), connection.display_name) for connection in connections
        ]

    def clean_spreadsheet(self) -> str:
        raw = str(self.cleaned_data["spreadsheet"])
        if match := _SPREADSHEET_URL_ID_RE.search(raw):
            return match.group(1)
        if _SPREADSHEET_ID_RE.fullmatch(raw):
            return raw
        raise forms.ValidationError(
            _("Enter a Google Sheets link or a spreadsheet ID.")
        )
