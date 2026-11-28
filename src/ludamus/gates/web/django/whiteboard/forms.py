from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.pacts.board import BOARD_TITLE_MAX_LENGTH


class BoardForm(forms.Form):
    title = forms.CharField(
        label=_("Board name"),
        max_length=BOARD_TITLE_MAX_LENGTH,
        help_text=_("Everyone at the board sees this name."),
    )
    room_link = forms.CharField(
        label=_("Little Table link"),
        max_length=500,
        help_text=_("Open the board on Little Table and copy its address here."),
        widget=forms.URLInput(attrs={"inputmode": "url", "autocomplete": "off"}),
    )
