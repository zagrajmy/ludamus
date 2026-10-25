from typing import TYPE_CHECKING, Any

from django import forms
from django.utils.translation import gettext, pgettext_lazy
from django.utils.translation import gettext_lazy as _

from ludamus.gates.uploads import validate_uploaded_image
from ludamus.gates.web.django.forms import ToggleRadioSelect, cover_image_field
from ludamus.pacts.listing import (
    LISTING_TEXT_MAX_LENGTH,
    LISTING_TITLE_MAX_LENGTH,
    ListingContact,
    ListingSeeking,
)

if TYPE_CHECKING:
    from ludamus.pacts.tags import TagCategoryOptionsDTO

SEEKING_LABELS = {
    ListingSeeking.PLAYERS: _("Looking for players"),
    ListingSeeking.GM: _("Looking for a GM"),
}

SEEKING_CHOICES = (
    (ListingSeeking.PLAYERS, pgettext_lazy("listing seeking", "Players")),
    (ListingSeeking.GM, pgettext_lazy("listing seeking", "GM")),
)

CONTACT_CHOICES = (
    (ListingContact.DISCORD, _("Discord")),
    (ListingContact.EMAIL, _("Account email")),
)


class ListingForm(forms.Form):
    seeking = forms.ChoiceField(
        label=_("Looking for"), choices=SEEKING_CHOICES, widget=ToggleRadioSelect
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
        help_text=_("For example: every other Friday evening, or to be agreed."),
    )
    medium = forms.CharField(
        label=_("Format"),
        max_length=LISTING_TEXT_MAX_LENGTH,
        required=False,
        help_text=_("For example: online, or in person."),
    )
    place = forms.CharField(
        label=_("Where"),
        max_length=LISTING_TEXT_MAX_LENGTH,
        required=False,
        help_text=_("For example: our Discord server, a café in Kraków, or my place."),
    )
    seats = forms.IntegerField(
        label=pgettext_lazy("listing", "Seats"),
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
        contact_channels: list[ListingContact],
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
        # NOTE: only channels on the profile are offered, and a single choice
        # renders as no picker. With none, both stay so a draft can still save.
        choices = [
            choice for choice in CONTACT_CHOICES if choice[0] in contact_channels
        ] or list(CONTACT_CHOICES)
        self.fields["contact"] = forms.ChoiceField(
            label=_("Contact"),
            choices=choices,
            initial=choices[0][0] if len(choices) == 1 else None,
            widget=forms.RadioSelect,
            help_text=(
                _("Shown only to the people in the party you form.")
                if contact_channels
                else _(
                    "Add your Discord username or an email address to your "
                    "profile before you publish."
                )
            ),
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
