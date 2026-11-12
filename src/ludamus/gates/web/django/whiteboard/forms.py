from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.pacts.board import BOARD_TITLE_MAX_LENGTH


class BoardRenameForm(forms.Form):
    title = forms.CharField(
        label=_("Board name"),
        max_length=BOARD_TITLE_MAX_LENGTH,
        help_text=_("Everyone at the board sees this name."),
    )
