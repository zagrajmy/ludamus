from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.forms import logo_field
from ludamus.gates.web.django.sphere.roles import ROLE_COPY
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.team import INVITATION_NOTE_MAX_LENGTH


class GuildForm(forms.Form):
    name = forms.CharField(label=_("Guild name"), max_length=255, strip=True)
    logo = logo_field(
        help_text=_(
            "The mark shown beside members' names on programme cards. Square, "
            "one colour, no lettering — it renders as small as 14 px. Max 8 MB. "
            "SVG, PNG, WebP, JPG, or AVIF."
        )
    )


class GuildMemberForm(forms.Form):
    identifier = forms.CharField(
        label=_("Name, email or Discord username"),
        help_text=_(
            "Imported presenters have no account — pick them by the name on the "
            "programme."
        ),
        widget=forms.TextInput(
            attrs={"list": "guild-presenter-suggestions", "autocomplete": "off"}
        ),
    )


class FacilitatorAssignGuildForm(forms.Form):
    guild_pk = forms.IntegerField(min_value=1)


class SphereInvitationForm(forms.Form):
    role = forms.ChoiceField(
        label=_("Role"),
        choices=[(role.value, copy.choice) for role, copy in ROLE_COPY.items()],
        initial=SphereRole.MANAGER.value,
        widget=forms.RadioSelect,
    )
    note = forms.CharField(
        label=_("Who is it for?"),
        required=False,
        max_length=INVITATION_NOTE_MAX_LENGTH,
        strip=True,
        help_text=_("Only you and other managers see this."),
        widget=forms.TextInput(attrs={"placeholder": _("e.g. Kasia, programme")}),
    )
