from typing import TYPE_CHECKING

from django import template

from ludamus.gates.web.django.board.forms import SEEKING_LABELS

if TYPE_CHECKING:
    from ludamus.pacts.listing import ListingDTO

register = template.Library()


@register.filter
def seeking_label(listing: ListingDTO) -> str:
    return str(SEEKING_LABELS[listing.seeking])
