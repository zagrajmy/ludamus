from typing import TYPE_CHECKING, Any

from django import forms
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from ludamus.gates.uploads import validate_uploaded_image
from ludamus.gates.web.django.forms import cover_image_field
from ludamus.pacts.listing import (
    LISTING_PAIRS,
    LISTING_TEXT_MAX_LENGTH,
    LISTING_TITLE_MAX_LENGTH,
    ListingContact,
    ListingRole,
    ListingSeeking,
)

if TYPE_CHECKING:
    from ludamus.pacts.tags import TagCategoryOptionsDTO

PAIR_LABELS = dict(
    zip(
        LISTING_PAIRS,
        (
            _("GM looking for players"),
            _("Player looking for a GM"),
            _("Player looking for a group"),
            _("Group looking for players"),
            _("Group looking for a GM"),
        ),
        strict=True,
    )
)


def pair_value(role: ListingRole, seeking: ListingSeeking) -> str:
    return f"{role}:{seeking}"


def split_pair(value: str) -> tuple[ListingRole, ListingSeeking]:
    role, seeking = value.split(":")
    return ListingRole(role), ListingSeeking(seeking)


CONTACT_CHOICES = (
    (ListingContact.DISCORD, _("Discord")),
    (ListingContact.EMAIL, _("Account email")),
)


class ListingForm(forms.Form):
    pair = forms.ChoiceField(
        label=_("Who is looking for whom"),
        choices=[(pair_value(*pair), label) for pair, label in PAIR_LABELS.items()],
        widget=forms.RadioSelect,
    )
    title = forms.CharField(label=_("Title"), max_length=LISTING_TITLE_MAX_LENGTH)
    what = forms.CharField(
        label=_("What we'll do"),
        max_length=LISTING_TEXT_MAX_LENGTH,
        help_text=_("For example: a Mörk Borg campaign, or painting D&D minis."),
    )
    description = forms.CharField(
        label=_("Description"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=_("Supports Markdown formatting."),
    )
    starts_at = forms.DateTimeField(
        label=_("Date and time"),
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
    )
    when_text = forms.CharField(
        label=_("When, in your words"),
        max_length=LISTING_TEXT_MAX_LENGTH,
        required=False,
        help_text=_(
            "Required without a date and time. For example: every other Friday "
            "evening, or to be agreed."
        ),
    )
    medium = forms.CharField(
        label=_("Online or offline"),
        max_length=LISTING_TEXT_MAX_LENGTH,
        required=False,
        help_text=_("For example: online on Discord, or at my place."),
    )
    place = forms.CharField(
        label=_("Where"), max_length=LISTING_TEXT_MAX_LENGTH, required=False
    )
    seats = forms.IntegerField(
        label=_("Seats"),
        min_value=1,
        max_value=99,
        required=False,
        help_text=_("Only informs; nobody is turned away when they fill up."),
    )
    header_image = cover_image_field(crop="top-and-bottom")

    def __init__(
        self,
        *args: Any,
        tag_categories: list[TagCategoryOptionsDTO],
        has_discord: bool,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.tag_categories = tag_categories
        self.fields["tags"] = forms.TypedMultipleChoiceField(
            label=_("Tags"),
            coerce=int,
            required=False,
            choices=[
                (option.pk, option.path)
                for category in tag_categories
                for option in category.options
            ],
        )
        # NOTE: Discord comes from the profile; without it the account email
        # is the one contact left, and a single choice renders as no picker.
        self.fields["contact"] = forms.ChoiceField(
            label=_("Contact"),
            choices=CONTACT_CHOICES if has_discord else CONTACT_CHOICES[1:],
            initial=None if has_discord else ListingContact.EMAIL,
            widget=forms.RadioSelect,
            help_text=_("Shown only to the people in the party you form."),
        )

    def clean_header_image(self) -> object:
        image = self.cleaned_data.get("header_image")
        validate_uploaded_image(image)
        return image

    def clean(self) -> dict[str, Any] | None:
        if (
            (cleaned := super().clean())
            and not cleaned.get("starts_at")
            and not cleaned.get("when_text")
        ):
            self.add_error(
                "when_text", gettext("Give a date and time, or describe when.")
            )
        return cleaned
