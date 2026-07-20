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
from .copy import copy_lines, tessera_copy, tessera_copy_chip, tessera_copy_popover
from .form import tessera_button, tessera_errors, tessera_field, tessera_form
from .icon import icon
from .icon_toggle import tessera_icon_toggle
from .radio import RadioNode, do_radio
from .select import SelectNode, do_select
from .switcher import SegmentNode, SwitcherNode, tessera_segment, tessera_switcher
from .tab_shell import TabShellBodyNode, TabShellNode, tab_shell, tab_shell_body
from .table import TableNode, do_tessera_table
from .tabs import TabNode, TabsNode, do_tab, do_tabs

__all__ = [
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
    "do_radio",
    "do_select",
    "do_tab",
    "do_tabs",
    "do_tessera_table",
    "icon",
    "register",
    "tab_shell",
    "tab_shell_body",
    "tessera_button",
    "tessera_copy",
    "tessera_copy_chip",
    "tessera_copy_popover",
    "tessera_errors",
    "tessera_field",
    "tessera_form",
    "tessera_icon_toggle",
    "tessera_segment",
    "tessera_switcher",
]
