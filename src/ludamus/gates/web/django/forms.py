"""Django forms for panel views."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from ludamus.gates.uploads import validate_uploaded_image, validate_uploaded_logo
from ludamus.gates.web.django.dynamic_fields import (
    CustomAnswerFormMixin,
    build_dynamic_fields,
)
from ludamus.gates.web.django.sphere.pages import SPHERE_PAGE_LABELS
from ludamus.pacts.discounts import DiscountKind
from ludamus.pacts.durations import (
    MAX_DURATION_HOURS,
    MAX_DURATION_MINUTES,
    build_duration,
    duration_choices,
)
from ludamus.pacts.images import IMAGE_ACCEPT, LOGO_ACCEPT, CoverCrop
from ludamus.pacts.legacy import EncounterPublicPolicy, PromotionMode, SpherePage
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from django.utils.functional import _StrPromise

    from ludamus.pacts import SessionFieldRequirementDTO
    from ludamus.pacts.multiverse import ConnectionDTO

_DATETIME_LOCAL_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]
# The hero prints the address under the venue name, where a third line
# pushes the CTAs off a phone screen.
MAX_ADDRESS_LINES = 2
# Hand-written rather than joined from IMAGE_FORMATS: it is translated user copy,
# and a comma-joined list of MIME types reads nothing like a sentence. Two of
# them because the two cover families are cropped along different axes; the
# dropzone guide (components/file-dropzone.html) draws the matching shape.
COVER_IMAGE_HELP_TEXT = _(
    "1920×1080 (16:9) works best. We crop the edges, so keep the subject in "
    "the middle and leave text out. Max 8 MB. JPG, PNG, WebP, or AVIF."
)
STRIP_COVER_IMAGE_HELP_TEXT = _(
    "1920×1080 (16:9) works best. We crop the top and bottom, so keep the "
    "subject in the middle and leave text out. Max 8 MB. JPG, PNG, WebP, or AVIF."
)
# Width of the PositiveIntegerField column on Postgres (`integer`). Dev sqlite
# is wider, so an overflow only ever surfaces in production. A validator rather
# than `max_value` on every field writing the column: validators reject
# server-side without renting a max attribute on the input. Without it the
# panel falls back to its generic "couldn't save" (its savepoint converts the
# DataError) and the facilitator self-edit, which catches nothing, 500s.
MAX_STORED_PARTICIPANTS_LIMIT = 2_147_483_647
STORAGE_LIMIT_VALIDATOR = MaxValueValidator(
    MAX_STORED_PARTICIPANTS_LIMIT, message=_("Enter a smaller number.")
)


class DropzoneFileInput(forms.ClearableFileInput):
    # `fit` and `safe_zone` are read by the tessera dropzone renderer, never
    # written to the input: they say how the preview frames the file, which is
    # the renderer's business and not the browser's.
    def __init__(
        self,
        *,
        attrs: dict[str, str] | None = None,
        fit: Literal["cover", "contain"] = "cover",
        safe_zone: CoverCrop | None = None,
    ) -> None:
        super().__init__(attrs)
        self.fit = fit
        # A crop guide over a preview that crops nothing would point at nothing.
        self.safe_zone = safe_zone if fit == "cover" else None


def cover_image_field(*, crop: CoverCrop) -> forms.ImageField:
    # Shared definition so every cover/header upload field stays identical
    # (label, limits, accepted types) without copy-pasting the declaration.
    # `crop` picks which surfaces this upload lands on, and with it both the
    # help text and the guide the dropzone draws over the preview.
    return forms.ImageField(
        label=_("Cover image"),
        required=False,
        help_text=(
            COVER_IMAGE_HELP_TEXT if crop == "edges" else STRIP_COVER_IMAGE_HELP_TEXT
        ),
        widget=DropzoneFileInput(attrs={"accept": IMAGE_ACCEPT}, safe_zone=crop),
    )


def logo_field(*, help_text: str | _StrPromise | None = None) -> forms.FileField:
    # Public like cover_image_field(): the guild panel lives in another module
    # and must not restate the accepted types or the contain-fit hint.
    return forms.FileField(
        required=False,
        label=_("Logo"),
        # Attached here rather than in each form's clean_logo: a logo field
        # cannot then exist without its validation. Django short-circuits the
        # False (clear) case before validators run, and validate_uploaded_logo
        # early-returns on empty, so behaviour is unchanged.
        validators=[validate_uploaded_logo],
        help_text=help_text
        or _(
            "Shown on the printable schedule. Max 8 MB. JPG, PNG, WebP, AVIF, or SVG."
        ),
        widget=DropzoneFileInput(attrs={"accept": LOGO_ACCEPT}, fit="contain"),
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
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
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

    cover_image = cover_image_field(crop="edges")
    logo = logo_field()
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


_PAGE_VALUES = {page.value for page in SpherePage}


def _sphere_page_choices() -> list[tuple[str, _StrPromise]]:
    return [(page.value, SPHERE_PAGE_LABELS[page]) for page in SpherePage]


class SphereSettingsForm(forms.Form):
    """Form for sphere-wide settings."""

    allow_facilitator_session_edit = forms.BooleanField(
        required=False,
        label=_("Allow facilitators to edit their own sessions"),
        help_text=_("Default for the whole sphere. Events can override this setting."),
    )
    enabled_pages = forms.MultipleChoiceField(
        choices=_sphere_page_choices,
        widget=forms.CheckboxSelectMultiple,
        label=_("Enabled pages"),
        error_messages={"required": _("At least one page must stay enabled.")},
    )
    default_page = forms.ChoiceField(
        choices=_sphere_page_choices,
        widget=forms.RadioSelect,
        label=_("Default page"),
        help_text=_("Shown when visitors open the sphere's homepage."),
    )
    encounter_public_policy = forms.ChoiceField(
        choices=[
            (
                EncounterPublicPolicy.DISABLED.value,
                _("Nobody (public encounters disabled)"),
            ),
            (EncounterPublicPolicy.MANAGERS.value, _("Sphere managers only")),
            (EncounterPublicPolicy.EVERYONE.value, _("Everyone")),
        ],
        widget=forms.RadioSelect,
        label=_("Who may make an encounter public"),
        help_text=_(
            "Public encounters are listed for everyone on the encounters page "
            "and the timeline."
        ),
    )
    # The pages the manager was warned about and confirmed, comma-separated.
    # A bare boolean would carry a confirmation for one page over to a page
    # they picked afterwards and were never warned about.
    confirmed_page_disable = forms.CharField(required=False, widget=forms.HiddenInput)
    logo = logo_field()

    def confirmed_pages(self) -> set[SpherePage]:
        raw: str = self.cleaned_data.get("confirmed_page_disable") or ""
        return {SpherePage(value) for value in raw.split(",") if value in _PAGE_VALUES}

    def clean(self) -> dict[str, Any] | None:
        # Also enforced by SpherePanelService.update_settings; repeated here so
        # the manager gets the message on the field rather than an exception.
        super().clean()
        default_page = self.cleaned_data.get("default_page")
        enabled_pages: list[str] = self.cleaned_data.get("enabled_pages") or []
        if default_page and default_page not in enabled_pages:
            self.add_error(
                "default_page", _("The default page must be one of the enabled pages.")
            )
        return self.cleaned_data


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
        if cleaned.get(
            "promotion_mode"
        ) == PromotionMode.OFFER_CLAIM.value and not cleaned.get(
            "offer_claim_window_minutes"
        ):
            self.add_error(
                "offer_claim_window_minutes",
                _("Set how long a held seat waits for confirmation."),
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
        help_text=_(
            "Public tracks are shown to proposers in the submission wizard, and"
            " their sessions appear on the event schedule."
        ),
    )


CUSTOM_DURATION = "custom"


class SessionEditForm(forms.Form):
    title = forms.CharField(
        max_length=255,
        strip=True,
        label=_("Title"),
        error_messages={"required": _("Title is required.")},
    )
    display_name = forms.CharField(
        max_length=255,
        strip=True,
        label=_("Display Name"),
        error_messages={"required": _("Display name is required.")},
    )
    description = forms.CharField(
        required=False, label=_("Description"), widget=forms.Textarea(attrs={"rows": 5})
    )
    contact_email = forms.EmailField(required=False, label=_("Contact Email"))
    participants_limit = forms.IntegerField(
        required=False,
        min_value=0,
        validators=[STORAGE_LIMIT_VALIDATOR],
        label=_("Participants Limit"),
        help_text=_("Empty or 0 = no enrollment"),
    )
    min_age = forms.IntegerField(required=False, min_value=0, label=_("Minimum Age"))
    # Not a field: the name a subclass's picker takes. Declared so the shared
    # duration partial can ask whether there is one to render.
    duration = None
    duration_hours = forms.IntegerField(
        required=False, min_value=0, max_value=MAX_DURATION_HOURS, label=_("Hours")
    )
    duration_minutes = forms.IntegerField(
        required=False, min_value=0, max_value=MAX_DURATION_MINUTES, label=_("Minutes")
    )
    cover_image = cover_image_field(crop="top-and-bottom")

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image

    # Returns nothing: the composed value is written straight into
    # cleaned_data, which Django keeps when clean() returns None.
    def clean(self) -> None:
        super().clean()
        cleaned = self.cleaned_data
        if "duration" in self.fields and cleaned.get("duration") != CUSTOM_DURATION:
            return
        cleaned["duration"] = build_duration(
            hours=cleaned.get("duration_hours") or 0,
            minutes=cleaned.get("duration_minutes") or 0,
        )
        # Picking "Custom" and entering nothing is a mistake worth naming; with
        # no preset picker at all the duration simply stays unset.
        if not cleaned["duration"] and "duration" in self.fields:
            self.add_error("duration", _("Enter how long the session lasts."))


def _duration_field(durations: Sequence[str]) -> forms.ChoiceField | None:
    # No configured durations means the steppers are the whole control, so no
    # picker is added at all.
    if not (labelled := duration_choices(durations)):
        return None
    return forms.ChoiceField(
        required=False,
        label=_("Duration"),
        choices=[
            ("", "---"),
            *labelled,
            # Kept last: the template reveals the steppers with a CSS
            # :last-child selector rather than JavaScript.
            (CUSTOM_DURATION, _("Custom")),
        ],
    )


# Takes durations rather than the category: a category's participant bounds bind
# the submission wizard only (event.propose_forms.build_session_details_form).
def create_proposal_form(
    categories: list[tuple[int, str]],
    *,
    requirements: Sequence[SessionFieldRequirementDTO] = (),
    durations: Sequence[str] = (),
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

    custom_required = build_dynamic_fields(
        fields=attrs, requirements=requirements, prefix="session"
    )

    namespace: dict[str, forms.Field | tuple[str, ...] | None] = {
        **attrs,
        "duration": _duration_field(durations),
        "custom_required_keys": custom_required,
    }
    return type(
        "ProposalCreateForm", (CustomAnswerFormMixin, SessionEditForm), namespace
    )


ACCREDITATION_TYPE_LABELS = {
    AccreditationType.NONE: _("None"),
    AccreditationType.STANDARD: _("Standard"),
    AccreditationType.GUEST: _("Guest"),
    AccreditationType.HONORARY: _("Honorary"),
    AccreditationType.CREATOR: _("Program creator"),
}
ACCREDITATION_TYPE_CHOICES = [
    (t.value, ACCREDITATION_TYPE_LABELS[t]) for t in AccreditationType
]


class FacilitatorFieldsForm(forms.Form):
    # Shared by the create and edit pages; both render fields by name, so the
    # declaration order here does not reach the templates.
    accreditation_type = forms.ChoiceField(
        choices=ACCREDITATION_TYPE_CHOICES,
        initial=AccreditationType.NONE,
        required=False,
        label=_("Accreditation type"),
    )
    is_collective = forms.BooleanField(
        required=False,
        label=_("Runs program points in parallel"),
        help_text=_(
            "For a guild or the organizer crew — the timetable stops reporting"
            " this facilitator's overlapping program points as a clash."
        ),
    )

    def clean_accreditation_type(self) -> str:
        return self.cleaned_data.get("accreditation_type") or AccreditationType.NONE


class FacilitatorForm(FacilitatorFieldsForm):
    """Form for creating a facilitator (display_name is required at creation)."""

    display_name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={
            "max_length": _("Display name is too long (max 255 characters)."),
            "required": _("Display name is required."),
        },
    )
    assign_me = forms.BooleanField(
        initial=True,
        required=False,
        label=_("Assign me as organizer"),
        help_text=_("You handle this facilitator until you step down."),
    )


class FacilitatorEditForm(FacilitatorFieldsForm):
    # No display_name: it is a read-only cache (the canonical byline lives on
    # the session), so the panel edit form only touches accreditation_type.
    internal_comment = forms.CharField(
        required=False,
        strip=True,
        widget=forms.Textarea(attrs={"rows": 3}),
        label=_("Internal comment"),
        help_text=_("Visible to organizers only."),
    )


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
        # Django derives step="0.01" from decimal_places; combined with
        # min="0.01" the browser's float step check rejects plain 50 and
        # suggests 50.01. step="any" drops it; the server still enforces 2dp.
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "any"}),
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
    tab = forms.CharField(
        label=_("Tab name"),
        max_length=100,
        strip=True,
        help_text=_("The tab has to exist already; the export replaces its content."),
    )
    columns = forms.MultipleChoiceField(
        label=_("Columns"),
        widget=forms.CheckboxSelectMultiple,
        help_text=_(
            "Facilitator and personal data written before the discount columns."
            " Pick what this sheet needs; nothing is exported by default."
        ),
    )

    def __init__(
        self,
        *args: Any,
        connections: Iterable[ConnectionDTO],
        columns: Iterable[tuple[str, str]] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        connection_field = cast("forms.ChoiceField", self.fields["connection"])
        connection_field.choices = [
            (str(connection.pk), connection.display_name) for connection in connections
        ]
        columns_field = cast("forms.MultipleChoiceField", self.fields["columns"])
        columns_field.choices = list(columns)

    def clean_spreadsheet(self) -> str:
        raw = str(self.cleaned_data["spreadsheet"])
        if match := _SPREADSHEET_URL_ID_RE.search(raw):
            return match.group(1)
        if _SPREADSHEET_ID_RE.fullmatch(raw):
            return raw
        raise forms.ValidationError(
            _("Enter a Google Sheets link or a spreadsheet ID.")
        )
