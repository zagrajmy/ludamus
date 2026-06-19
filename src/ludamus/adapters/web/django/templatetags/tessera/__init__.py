"""Tessera design-system template tags.

Usage:
    {% load tessera %}

    {% icon "calendar" %}
    {% icon "calendar" variant="solid" class="w-5 h-5" %}

    {% select id="color" name="color" required=True %}
        <option value="">Pick one...</option>
    {% end_select %}

    {% tabs %}
        {% tab "home" icon="home" href="/home/" active=True %}Home{% end_tab %}
    {% end_tabs %}

    {% tessera_form form %}
    {% tessera_field form.name %}
    {% tessera_button "Submit" %}
    {% tessera_errors form %}
"""

from ._registry import register
from .form import tessera_button, tessera_errors, tessera_field, tessera_form
from .icon import icon
from .select import SelectNode, do_select
from .table import TableNode, do_tessera_table
from .tabs import (
    TAB_ACTIVE_CLASS,
    TAB_INACTIVE_CLASS,
    TAB_NAV_CLASS,
    TabNode,
    TabsNode,
    do_tab,
    do_tabs,
)

__all__ = [
    "TAB_ACTIVE_CLASS",
    "TAB_INACTIVE_CLASS",
    "TAB_NAV_CLASS",
    "SelectNode",
    "TabNode",
    "TableNode",
    "TabsNode",
    "do_select",
    "do_tab",
    "do_tabs",
    "do_tessera_table",
    "icon",
    "register",
    "tessera_button",
    "tessera_errors",
    "tessera_field",
    "tessera_form",
]
