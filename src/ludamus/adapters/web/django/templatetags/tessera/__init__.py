"""Tessera design-system template tags.

Usage:
    {% load tessera %}

    {% icon "calendar" %}
    {% icon "calendar" variant="solid" class="w-5 h-5" %}

    {% select id="color" name="color" required=True %}
        <option value="">Pick one...</option>
    {% endselect %}

    {% tessera_combobox id="host" name="host" %}
        <option value="">Everyone</option>
    {% endtessera_combobox %}

    {% tabs %}
        {% tab "home" icon="home" href="/home/" active=True %}Home{% endtab %}
    {% endtabs %}

    {% tessera_form form %}
    {% tessera_field form.name %}
    {% tessera_button "Submit" %}
    {% tessera_errors form %}
"""

from ._registry import register
from .action_dropdown import (
    ActionDropdownNode,
    do_action_dropdown,
    tessera_action_dropdown_item,
)
from .combobox import ComboboxNode, do_combobox
from .copy import copy_lines, tessera_copy, tessera_copy_chip, tessera_copy_popover
from .dynamic_field import dynamic_field
from .form import tessera_button, tessera_errors, tessera_field, tessera_form
from .icon import icon
from .icon_button import tessera_icon_button
from .icon_toggle import tessera_icon_toggle
from .radio import RadioNode, do_radio
from .select import SelectNode, do_select
from .switcher import SegmentNode, SwitcherNode, tessera_segment, tessera_switcher
from .tab_shell import TabShellBodyNode, TabShellNode, tab_shell, tab_shell_body
from .table import TableNode, do_tessera_table
from .tabs import TabNode, TabsNode, do_tab, do_tabs

__all__ = [
    "ActionDropdownNode",
    "ComboboxNode",
    "RadioNode",
    "SegmentNode",
    "SelectNode",
    "SwitcherNode",
    "TabNode",
    "TabShellBodyNode",
    "TabShellNode",
    "TableNode",
    "TabsNode",
    "copy_lines",
    "do_action_dropdown",
    "do_combobox",
    "do_radio",
    "do_select",
    "do_tab",
    "do_tabs",
    "do_tessera_table",
    "dynamic_field",
    "icon",
    "register",
    "tab_shell",
    "tab_shell_body",
    "tessera_action_dropdown_item",
    "tessera_button",
    "tessera_copy",
    "tessera_copy_chip",
    "tessera_copy_popover",
    "tessera_errors",
    "tessera_field",
    "tessera_form",
    "tessera_icon_button",
    "tessera_icon_toggle",
    "tessera_segment",
    "tessera_switcher",
]
