"""{% tessera_link_tile %} — one of a few big links, each saying where it goes."""

from __future__ import annotations

from ._registry import register


@register.inclusion_tag("components/link_tile.html")
def tessera_link_tile(
    *, id_prefix: str, href: str, title: str, description: str, icon: str
) -> dict[str, str]:
    """Render a link tile: a title, a line of help and an icon.

    The link is named by its title and described by its help through ids
    that start with ``id_prefix``, so the prefix must be unique on the page.

    Returns:
        The context for ``components/link_tile.html``.

    Usage:
        {% tessera_link_tile id_prefix="x" href=u title=t description=d icon="map" %}
    """
    return {
        "id_prefix": id_prefix,
        "href": href,
        "title": title,
        "description": description,
        "icon": icon,
    }
