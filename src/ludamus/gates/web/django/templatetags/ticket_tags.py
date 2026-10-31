from __future__ import annotations

import base64
from decimal import Decimal

from django import template
from django.utils import formats

from ludamus.mills.qr import qr_svg
from ludamus.pacts.tickets import DEFAULT_CURRENCY, MONEY_DECIMAL_PLACES

register = template.Library()

_SYMBOLS = {"pln": "zł"}


@register.filter
def money(amount: int, currency: str = DEFAULT_CURRENCY) -> str:
    """Render minor units as the locale writes money: 1750 → "17,50 zł"."""
    value = formats.number_format(
        Decimal(amount).scaleb(-MONEY_DECIMAL_PLACES),
        decimal_pos=MONEY_DECIMAL_PLACES,
        use_l10n=True,
        force_grouping=True,
    )
    symbol = _SYMBOLS.get(currency.lower(), currency.upper())
    # NBSP: the amount and its currency never wrap apart.
    return f"{value}\N{NO-BREAK SPACE}{symbol}"


@register.filter
def qr_data_url(code: str) -> str:
    """Render a ticket code as a QR image URL, for whoever checks tickets."""
    svg = qr_svg(code, scale=5, xmldecl=False)
    return f"data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}"
