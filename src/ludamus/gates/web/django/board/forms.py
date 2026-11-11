from typing import TYPE_CHECKING, Any

from django import forms
from django.utils.translation import gettext, pgettext_lazy
from django.utils.translation import gettext_lazy as _

from ludamus.gates.uploads import validate_uploaded_image
from ludamus.gates.web.django.forms import (
    MarkdownTextarea,
    ToggleRadioSelect,
    cover_image_field,
)
from ludamus.pacts.listing import (
    LISTING_MESSAGE_MAX_LENGTH,
    LISTING_TEXT_MAX_LENGTH,
    LISTING_TITLE_MAX_LENGTH,
    ListingContact,
    ListingSeeking,
)

if TYPE_CHECKING:
    from django.http import QueryDict
    from django.utils.functional import _StrPromise

    from ludamus.pacts.listing import BoardFiltersDict
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


# What the viewer wants, keyed to what a listing seeks: a listing seeking
# players offers a game to join, one seeking a GM offers players.
LOOKING_FOR = {"game": ListingSeeking.PLAYERS, "players": ListingSeeking.GM}

ANYTHING = "any"
BOARD_SEARCH_MAX_LENGTH = 100


class BoardFilterForm(forms.Form):
    looking_for = forms.ChoiceField(
        label=_("What are you looking for?"),
        required=False,
        choices=(
            (ANYTHING, pgettext_lazy("board looking for", "Anything")),
            ("game", pgettext_lazy("board looking for", "A game to join")),
            ("players", pgettext_lazy("board looking for", "Players")),
        ),
        widget=ToggleRadioSelect,
    )
    q = forms.CharField(
        label=_("Search"),
        required=False,
        max_length=BOARD_SEARCH_MAX_LENGTH,
        widget=forms.TextInput(
            attrs={"type": "search", "placeholder": _("Title or what you'll do")}
        ),
    )
    closed = forms.BooleanField(label=_("Show closed"), required=False)
    # The facets draw these boxes; the field only reads the repeated ?tag=.
    tag = forms.Field(required=False, widget=forms.MultipleHiddenInput)

    def __init__(self, data: QueryDict) -> None:
        # A bound form ignores `initial`, and the toggle shows nothing picked
        # for an empty value, so "Anything" is filled in as if sent.
        data = data.copy()
        data.setdefault("looking_for", ANYTHING)
        super().__init__(data)

    def clean_tag(self) -> list[int]:
        return [int(raw) for raw in self.cleaned_data["tag"] or [] if raw.isdecimal()]

    def filters(self) -> BoardFiltersDict:
        # A filter that fails to parse is dropped, not reported: the query
        # string is a link someone may have edited by hand.
        self.is_valid()
        data = self.cleaned_data
        return {
            "seeking": LOOKING_FOR.get(data.get("looking_for", "")),
            "search": data.get("q", ""),
            "tag_ids": data.get("tag", []),
            "show_closed": data.get("closed", False),
        }


def contact_field(
    contact_channels: list[ListingContact], *, help_text: str | _StrPromise
) -> forms.ChoiceField:
    # NOTE: only channels on the profile are offered, and a single choice
    # renders as no picker. With none, both stay so the mill can say what to add.
    choices = [
        choice for choice in CONTACT_CHOICES if choice[0] in contact_channels
    ] or list(CONTACT_CHOICES)
    return forms.ChoiceField(
        label=_("Contact"),
        choices=choices,
        initial=choices[0][0] if len(choices) == 1 else None,
        widget=forms.RadioSelect,
        help_text=help_text,
    )


class ListingResponseForm(forms.Form):
    message = forms.CharField(
        label=_("Message"),
        required=False,
        max_length=LISTING_MESSAGE_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Optional. Say a few words about yourself."),
    )

    def __init__(
        self, data: QueryDict | None = None, *, contact_channels: list[ListingContact]
    ) -> None:
        super().__init__(data)
        self.fields["contact"] = contact_field(
            contact_channels,
            help_text=_("Shown to the author once you join their party."),
        )


class ListingDeclineForm(forms.Form):
    message = forms.CharField(
        label=_("Message"),
        required=False,
        max_length=LISTING_MESSAGE_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=_("Optional. They see it in their notifications."),
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
        widget=MarkdownTextarea(published=False, attrs={"rows": 5}),
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
        self.fields["contact"] = contact_field(
            contact_channels,
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
