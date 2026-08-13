from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.forms import logo_field


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
