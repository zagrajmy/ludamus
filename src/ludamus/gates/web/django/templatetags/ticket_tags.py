from __future__ import annotations

from decimal import Decimal

from django import template
from django.utils import formats

from ludamus.pacts.tickets import DEFAULT_CURRENCY

register = template.Library()

_MINOR_UNITS = 100
_SYMBOLS = {"pln": "zł"}


@register.filter
def money(amount: int, currency: str = DEFAULT_CURRENCY) -> str:
    """Render minor units as the locale writes money: 1750 → "17,50 zł"."""
    value = formats.number_format(
        Decimal(amount) / _MINOR_UNITS,
        decimal_pos=2,
        use_l10n=True,
        force_grouping=True,
    )
    symbol = _SYMBOLS.get(currency.lower(), currency.upper())
    # NBSP: the amount and its currency never wrap apart.
    return f"{value}\N{NO-BREAK SPACE}{symbol}"
