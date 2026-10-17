from typing import TYPE_CHECKING

from django import template

from ludamus.gates.web.django.board.forms import PAIR_LABELS

if TYPE_CHECKING:
    from ludamus.pacts.listing import ListingDTO

register = template.Library()


@register.filter
def pair_label(listing: ListingDTO) -> str:
    return str(PAIR_LABELS[listing.role, listing.seeking])
