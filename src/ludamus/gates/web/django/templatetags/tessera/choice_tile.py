"""{% tessera_choice_tile %} — one of a few big links, each saying where it goes."""

from __future__ import annotations

from ._registry import register


@register.inclusion_tag("components/choice_tile.html")
def tessera_choice_tile(
    *, tile_id: str, href: str, title: str, description: str, icon: str
) -> dict[str, str]:
    """Render a link tile: a title, a line of help and an icon.

    ``tile_id`` prefixes the ids that name the link by its title and describe
    it by its help, so it must be unique on the page.

    Returns:
        The context for ``components/choice_tile.html``.

    Usage:
        {% tessera_choice_tile tile_id="organize-event" href=url title=title
            description=help icon="calendar-days" %}
    """
    return {
        "tile_id": tile_id,
        "href": href,
        "title": title,
        "description": description,
        "icon": icon,
    }
